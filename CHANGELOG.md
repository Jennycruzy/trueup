# Changelog

## Unreleased

- Fake provider (`trueup.fake`) for OpenAI Chat Completions, OpenAI Responses and Anthropic Messages, with a truth log.
- Scenario library (`trueup.scenarios`): 31 plain-SDK scenarios; framework scenarios listed as not built.
- Runner (`trueup.runner`): one scenario per subprocess in a per-library uv venv (neatlogs, openinference, openllmetry), spans captured in memory.
- `trueup sweep <library>` writes observations to `.trueup/runs/<run_id>/`.
- Dev dependencies: `openai`, `anthropic`. Tests that spawn subprocesses are marked `e2e` and excluded by default.
- Project skeleton: uv project, `trueup` command, data model in `trueup.core`, `doctor` command, tests and CI.
