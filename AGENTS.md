# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

<!-- cspell:ignore virtualenv venv pytest mypy pyproject asyncio httpx litellm DEEPSEEK Jaccard setuptools -->

## Global rules

- Prefer the project virtual environment for all verification and local runs: use `./.venv/bin/...` when the shell is not already activated.
- `agent-ci-verify` is a local verification pipeline for agent output directories. The main flow is: `cli.py` parses flags → `config.py` loads and merges `.agent-ci.yaml` → `pipeline.py` runs built-in and plugin checkers → `types.py` normalizes results → terminal / JSON / HTML / history output is produced.
- Keep this file short; detailed repository guidance lives in `.Codex/rules/*.md`.

## Rules modules

- `.Codex/rules/development-commands.md` — common commands and CI verification commands.
- `.Codex/rules/core-pipeline.md` — config, pipeline, plugin, and report model architecture.
- `.Codex/rules/checker-system.md` — path-targeted checker responsibilities and test fixture expectations.
- `.Codex/rules/cli-and-reporting.md` — path-targeted CLI, output mode, history, and HTML report behavior.
