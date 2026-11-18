"""Sample product visibility through first-party model APIs."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from providers import PROVIDERS, parse_response, request_spec
from report import render, summarize


class RequestFailure(Exception):
    def __init__(self, reason, retryable=False, retry_after=0):
        super().__init__(reason)
        self.retryable = retryable
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value.strip()


def aliases(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return list(dict.fromkeys(required_text(item, label) for item in value))


def normalize(raw):
    if not isinstance(raw, dict):
        raise ValueError("configuration must be an object")
    brand = required_text(raw.get("brand"), "brand")
    questions = raw.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions must be a nonempty array")
    normalized_questions = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("each question must be an object")
        text = question.get("text")
        required_text(text, "question text")
        normalized_questions.append({
            "id": required_text(question.get("id"), "question id"),
            "language": required_text(question.get("language"), "question language").lower(),
            "text": text,
        })
    if len({question["id"] for question in normalized_questions}) != len(questions):
        raise ValueError("question ids must be unique")

    models = raw.get("models", [{"provider": name} for name in PROVIDERS])
    if not isinstance(models, list) or not models:
        raise ValueError("models must be a nonempty array")
    normalized_models = []
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("each model must be an object")
        name = required_text(model.get("provider"), "provider")
        provider = PROVIDERS.get(name)
        if provider is None:
            raise ValueError(f"unknown provider: {name}")
        model_id = model.get("model", provider.default_model)
        if model_id is not None:
            model_id = required_text(model_id, "model id")
        mode = model.get("mode", provider.modes[0])
        if mode not in ("plain", "search"):
            raise ValueError("model mode must be plain or search")
        normalized_models.append({"provider": name, "model": model_id, "mode": mode})
    if len({tuple(model.values()) for model in normalized_models}) != len(models):
        raise ValueError("provider, model and mode combinations must be unique")

    samples = raw.get("samples", 5)
    if type(samples) is not int or samples < 1:
        raise ValueError("samples must be a positive integer")
    language = raw.get("report_language", "zh")
    if language not in ("zh", "en"):
        raise ValueError("report_language must be zh or en")
    language_aliases = raw.get("language_aliases", {})
    if not isinstance(language_aliases, dict):
        raise ValueError("language_aliases must be an object")
    normalized_aliases = {}
    for code, names in language_aliases.items():
        code = required_text(code, "alias language").lower()
        normalized_aliases.setdefault(code, []).extend(aliases(names, "language aliases"))
    return {
        "brand": brand,
        "aliases": aliases(raw.get("aliases", []), "aliases"),
        "language_aliases": normalized_aliases,
        "questions": normalized_questions,
        "models": normalized_models,
        "samples": samples,
        "report_language": language,
    }


def availability(model):
    provider = PROVIDERS[model["provider"]]
    if model["mode"] not in provider.modes:
        return "unsupported_mode", None
    if model["model"] is None:
        return "missing_model", None
    key = os.environ.get(provider.key_env, "").strip()
    if not key:
        return "missing_key", None
    return "ready", key


def preview(config):
    slots = len(config["questions"]) * config["samples"]
    models = []
    for model in config["models"]:
        status, _ = availability(model)
        models.append({
            **model,
            "key_env": PROVIDERS[model["provider"]].key_env,
            "status": status,
            "planned_requests": slots,
        })
    return {
        "planned_requests": slots * len(models),
        "ready_requests": slots * sum(model["status"] == "ready" for model in models),
        "models": models,
    }


def post_json(url, headers, body):
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=120) as response:
            return json.load(response)
    except HTTPError as exc:
        retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
        wait = 0
        if retry_after.isascii() and retry_after.isdigit() and len(retry_after) <= 6:
            wait = min(int(retry_after), 60)
        exc.close()
        raise RequestFailure(
            f"http_{exc.code}",
            exc.code in (408, 429, 500, 502, 503, 504),
            wait,
        ) from None
    except (URLError, TimeoutError, ConnectionError, IncompleteRead):
        raise RequestFailure("network_error", retryable=True) from None
    except ValueError:
        raise RequestFailure("invalid_json") from None


def collect(model, question, key, transport):
    provider, model_id, mode = (model[field] for field in ("provider", "model", "mode"))
    try:
        request = request_spec(provider, model_id, mode, question, key)
    except ValueError:
        return {"status": "failed", "reason": "invalid_request"}
    for attempt in range(3):
        try:
            payload = transport(*request)
            if not isinstance(payload, dict):
                return {"status": "failed", "reason": "invalid_response"}
            return {**parse_response(provider, mode, payload), "status": "ok"}
        except RequestFailure as exc:
            if not exc.retryable or attempt == 2:
                return {"status": "failed", "reason": str(exc)}
            time.sleep(max(2 ** attempt, exc.retry_after))
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            return {"status": "failed", "reason": "invalid_response"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_atomic(path, content):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def execute(config, directory, *, resume=False, transport=post_json):
    directory.mkdir(parents=True, exist_ok=resume)
    database = directory / "run.sqlite3"
    if resume and not database.is_file():
        raise ValueError("run state does not exist")
    with (directory / ".lock").open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("this run is already in progress") from None
        with closing(sqlite3.connect(database)) as db:
            return execute_locked(config, directory, db, resume, transport)


def execute_locked(config, directory, db, resume, transport):
    # Report language can change when rebuilding a report from the same samples.
    signature = encode({key: value for key, value in config.items() if key != "report_language"})
    if resume:
        stored = db.execute("SELECT config FROM run").fetchone()
        if stored is None or signature != stored[0]:
            raise ValueError("resume requires the original run configuration")
    else:
        with db:
            db.execute("BEGIN")
            db.execute("CREATE TABLE run (config TEXT NOT NULL)")
            db.execute("CREATE TABLE samples (slot INTEGER PRIMARY KEY, row TEXT NOT NULL)")
            db.execute("INSERT INTO run VALUES (?)", (signature,))

    saved = {slot: json.loads(row) for slot, row in db.execute("SELECT slot, row FROM samples")}
    slot = 0
    for model in config["models"]:
        readiness, key = availability(model)
        for question in config["questions"]:
            for sample in range(1, config["samples"] + 1):
                slot += 1
                if saved.get(slot, {}).get("status") == "ok":
                    continue
                started = timestamp()
                if readiness == "ready":
                    result = collect(model, question["text"], key, transport)
                else:
                    result = {"status": "skipped", "reason": readiness}
                row = {
                    **model,
                    "question_id": question["id"],
                    "language": question["language"],
                    "sample": sample,
                    "timestamp": started,
                    **result,
                }
                with db:
                    db.execute("INSERT OR REPLACE INTO samples VALUES (?, ?)", (slot, encode(row)))
                saved[slot] = row
    rows = [saved[slot] for slot in sorted(saved)]
    report = summarize(config, rows)
    write_atomic(directory / "samples.jsonl", "".join(encode(row) + "\n" for row in rows))
    write_atomic(directory / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_atomic(directory / "report.md", render(report, config["report_language"]))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="UTF-8 JSON configuration")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preview", action="store_true", help="show planned requests without calling APIs")
    action.add_argument("--run-dir", type=Path, help="start a fresh run in a new directory")
    action.add_argument("--resume", type=Path, help="resume an existing run")
    args = parser.parse_args(argv)
    try:
        config = normalize(json.loads(args.config.read_text(encoding="utf-8")))
        if args.preview:
            print(json.dumps(preview(config), ensure_ascii=False, indent=2))
        else:
            directory = args.run_dir or args.resume
            report = execute(config, directory, resume=args.resume is not None)
            print(directory / "report.md")
            if report["valid_samples"] == 0:
                print("No valid answers. See the report for failed or skipped samples.", file=sys.stderr)
                return 2
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
