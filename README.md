# Brand in AI

English | [简体中文](README.zh-CN.md)

Brand in AI is a skill for measuring a brand or product's visibility in AI model answers. It sends user-supplied multilingual questions to providers' official APIs, independently samples answers, and summarizes brand mentions, recommendation ranks, and cited links.

## Requirements

- Linux, macOS, or Windows and Python 3.10 or later; no third-party Python dependencies are required.
- API credentials for the selected providers are required for sampling. Requests may incur charges.

## Quick start

For an agent that supports skills, install or copy `skills/brand-in-ai` into its skill directory according to the agent's instructions. For other agents, provide [SKILL.md](skills/brand-in-ai/SKILL.md) as instructions and give the agent access to the repository and Python. Installation and tool permissions depend on the agent.

1. Copy the example configuration and enter the brand, confirmed aliases, and questions:

   ```sh
   cp skills/brand-in-ai/references/example.json config.json
   ```

2. Edit `config.json` to select providers and models. Each question needs a unique `id`, a `language` tag, and its original `text`. `samples` defaults to five per question and model; set `report_language` to `zh` or `en`. Omitting `models` selects all registered providers.
3. Set the selected providers' environment variables, for example `export OPENAI_API_KEY="your-key"`. See [provider setup](skills/brand-in-ai/references/providers.md) for credentials, models, search modes, and regional requirements. Doubao requires an explicit model or inference endpoint ID.
4. Preview and run from the repository root:

   ```sh
   python3 skills/brand-in-ai/scripts/run.py config.json --preview
   python3 skills/brand-in-ai/scripts/run.py config.json --run-dir results/run-001
   ```

The preview does not call providers. To continue a particular run, keep its directory and use the original configuration:

On Windows PowerShell, use `Copy-Item` instead of `cp`, set credentials with `$env:OPENAI_API_KEY = "your-key"`, and use `python` (or `py`) in place of `python3` in the commands.

```sh
python3 skills/brand-in-ai/scripts/run.py config.json --resume results/run-001
```

## Results and interpretation

The run directory contains `report.md` (summary), `report.json` (statistics), and `samples.jsonl` (raw answers). Compare the same question set and search mode, and account for missing coverage. Distinguish questions that name the target brand from unaided mentions. Whether search actually occurred depends on evidence returned by the provider; requesting search alone does not establish that it ran.

See the [skill instructions](skills/brand-in-ai/SKILL.md) for the full workflow. As of 2026-11-18, live API verification for all twelve providers is pending; offline tests use hand-written fixtures. Check provider documentation and send a test request before a production run.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

---

Maintained by [GEOrca](https://georca.com).
