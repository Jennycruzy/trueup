# Changelog

## Unreleased

- Comparer (`trueup.core.compare`): checks run status, call status, call count, span closed, tokens, output and finish, with HIGH/MEDIUM/LOW severity. Records a library changing the request (such as adding `stream_options.include_usage`) as a LOW note.
- Adapters (`trueup.core.adapters`): one per library for neatlogs, OpenInference and OpenLLMetry, tested on saved span JSON in `tests/fixtures/spans/`.
- Reports (`trueup.core.report`): leads table and `leads.json`.
- `trueup sweep <library>` compares, prints the leads table, writes `leads.json`, and exits 1 if there is any lead.
- `trueup audit <script> --library <library>`: runs the script's `main()` against the fake through `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL`, once per fake scenario on each route it calls, and compares. Example script in `examples/agent.py`.
- The fake provider can be told which scenario to answer with on a route, whatever the model name.
- `Mismatch` has `check` and `kind` ("lead" or "note").
- Fake provider (`trueup.fake`) for OpenAI Chat Completions, OpenAI Responses and Anthropic Messages, with a truth log.
- Scenario library (`trueup.scenarios`): 31 plain-SDK scenarios; framework scenarios listed as not built.
- Runner (`trueup.runner`): one scenario per subprocess in a per-library uv venv (neatlogs, openinference, openllmetry), spans captured in memory.
- `trueup sweep <library>` writes observations to `.trueup/runs/<run_id>/`.
- Dev dependencies: `openai`, `anthropic`. Tests that spawn subprocesses are marked `e2e` and excluded by default.
- Project skeleton: uv project, `trueup` command, data model in `trueup.core`, `doctor` command, tests and CI.
