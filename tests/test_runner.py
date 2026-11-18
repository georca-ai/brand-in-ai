import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/brand-in-ai/scripts"))


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "brand": "Acme",
            "questions": [{"id": "q1", "language": "ja", "text": "おすすめは？"}],
            "models": [{"provider": "deepseek", "model": "test-model"}],
            "samples": 2,
        }

    def test_preview_detects_missing_credentials(self):
        import run

        with patch.dict(os.environ, clear=True):
            result = run.preview(run.normalize(self.config))
        self.assertEqual(result["planned_requests"], 2)
        self.assertEqual(result["ready_requests"], 0)

    def test_resume_retries_only_failed_slots_and_rejects_changed_input(self):
        import run

        calls = []

        def transport(url, headers, body):
            calls.append(body)
            if len(calls) == 2:
                raise run.RequestFailure("http_400")
            return {"model": "test-model", "choices": [{"message": {"content": "1. Acme"}, "finish_reason": "stop"}]}

        config = run.normalize(self.config)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "test"}, clear=True
        ):
            path = Path(directory) / "run"
            run.execute(config, path, transport=transport)
            first = [json.loads(line) for line in (path / "samples.jsonl").read_text().splitlines()]
            self.assertEqual([row["status"] for row in first], ["ok", "failed"])
            run.execute(config, path, resume=True, transport=transport)
            second = [json.loads(line) for line in (path / "samples.jsonl").read_text().splitlines()]
            self.assertEqual([row["status"] for row in second], ["ok", "ok"])
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0]["messages"], [{"role": "user", "content": "おすすめは？"}])
            self.assertIn("Acme", (path / "report.md").read_text())
            self.assertTrue((path / "report.json").exists())
            with self.assertRaises(ValueError):
                run.execute({**config, "samples": 3}, path, resume=True, transport=transport)

    def test_unsupported_modes_are_visible_and_do_not_call_api(self):
        import run

        self.config["models"][0]["mode"] = "search"
        config = run.normalize(self.config)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "test"}, clear=True
        ):
            path = Path(directory) / "run"
            run.execute(config, path, transport=lambda *_: self.fail("unexpected request"))
            rows = [json.loads(line) for line in (path / "samples.jsonl").read_text().splitlines()]
            self.assertEqual([row["reason"] for row in rows], ["unsupported_mode"] * 2)

    def test_resume_after_interruption_uses_the_committed_sample(self):
        import run

        answer = {"choices": [{"message": {"content": "Acme"}, "finish_reason": "stop"}]}
        config = run.normalize(self.config)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "test"}, clear=True
        ):
            path = Path(directory) / "run"
            with patch.object(run, "post_json", side_effect=[answer, KeyboardInterrupt]) as send:
                with self.assertRaises(KeyboardInterrupt):
                    run.execute(config, path, transport=send)
            with patch.object(run, "post_json", return_value=answer) as send:
                result = run.execute(config, path, resume=True, transport=send)
                self.assertEqual(send.call_count, 1)
            self.assertEqual(result["valid_samples"], 2)

    def test_transient_failures_have_a_bounded_retry(self):
        import run

        model = run.normalize(self.config)["models"][0]
        with patch.object(run, "post_json", side_effect=run.RequestFailure("http_429", True, 3)) as send:
            with patch.object(run.time, "sleep") as wait:
                result = run.collect(model, "おすすめは？", "key", send)
        self.assertEqual(send.call_count, 3)
        self.assertEqual([args[0] for args, _ in wait.call_args_list], [3, 3])
        self.assertEqual(result, {"status": "failed", "reason": "http_429"})

    def test_cli_keeps_report_but_signals_zero_valid_answers(self):
        import run

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, clear=True):
            path = Path(directory)
            config = path / "config.json"
            config.write_text(json.dumps(self.config), encoding="utf-8")
            output = path / "run"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(run.main([str(config), "--run-dir", str(output)]), 2)
            self.assertTrue((output / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
