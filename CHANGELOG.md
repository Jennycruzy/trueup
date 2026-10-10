# Changelog

## Unreleased

- `trueup check <run_id|latest> [--library x]`: runs the checker and the deduper over a sweep's leads and writes `findings.json`, `withdrawn.json` and `evidence.json` next to `leads.json`. Prints findings by severity, withdrawn by rule and already-known. Exits 1 if there is a finding.
- Checker (`trueup.core.checker`): seven rules, each a pure function over recorded evidence: fresh process twice, recommended setup, latest release and main branch, fake truthful, harness sane, reference (another library or the OTel conventions), and a repro under 40 lines. A lead is a finding only if every rule passes; otherwise it is withdrawn with the rule that failed, kept as a lead, or marked "disputed semantics". Withdrawn leads are kept and counted.
- Evidence gathering (`trueup.check`): upgrades the library's venv to the latest release and records versions against PyPI, reruns each scenario twice, builds `.trueup/venvs/<lib>-main` from a shallow clone of the library's main branch, reads the other libraries' latest sweeps, and generates and runs a repro per scenario (`repros/` in the run dir). Leads are compared again with today's adapters.
- Grouping (`trueup.core.group`): leads with the same library, check, field and code path become one finding with a list of scenarios.
- Deduper (`trueup.dedupe`): searches the library's GitHub issues and PRs in all states with `gh search issues --include-prs`, lists the integration's titles, records each search with its date and marks a finding "already known" with the link when a title names the integration and the behaviour. Read only.
- Repro generator (`trueup.core.repro`): a short script that runs a scenario offline under a library and prints its leads.
- Fix: the neatlogs adapter now also reads `llm.finish_reason`. neatlogs framework spans come from the OpenInference instrumentors and carry the finish reason only there. This removed 27 false finish leads.

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
