# Changelog

## Unreleased

- Framework scenarios: 20 built (LangChain 6, LangGraph 6, OpenAI Agents SDK 8), each with expected truth, including which tools ran and which raised. App code in `trueup.runner.framework_apps`.
- Fake provider: agent flows on Chat Completions and Responses. Tool call then answer, parallel tools, a tool loop, 500 on the second call, an unknown tool name, and an error event or a cut in the second streamed call.
- Runner: each library's setup per framework. neatlogs uses its README keys, OpenInference its LangChain and OpenAI Agents instrumentors, OpenLLMetry `Traceloop.init`. The framework packages, `langchain` included, are installed in every venv. A framework scenario is NOT RUN, with the reason, if the framework does not import or no instrumentor for it is active. The Agents SDK's own trace upload is turned off.
- Comparer: run status uses the trace root. New `tools` and `error_recorded` checks. OpenLLMetry framework spans (agent, task, tool, workflow) are no longer counted as LLM calls. A scenario can say the app asked for stream usage itself.
- `trueup sweep <library> --framework all|none|langchain|openai-agents`. The default is all.
- Dev dependencies: `langchain-openai`, `langgraph`, `openai-agents`.

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
