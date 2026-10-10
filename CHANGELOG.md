# Changelog

## Unreleased

- `trueup plan <lib> [--max N]` (default 5): the planner (`trueup.planner`) sends the library's wrapper source from its venv, the scenario library and the latest findings to `claude-sonnet-4.6`, and gets new scenarios back as JSON. Each proposal is checked by `trueup.scenarios.proposed`: schema, app exists, fake model supported on the app's route, app + model pair not already covered, expected truth only in fields the comparer checks, then an untraced run in a subprocess must give that truth. Rejected proposals go back to the model with the reason, at most 2 times; they are kept and counted in `plan.json`. Accepted ones are written to `scenarios/proposed/<lib>/<id>.json`. For chat proposals the app's own `include_usage` is taken from the untraced run.
- `trueup sweep <lib> --proposed [FROM]`: sweeps the accepted proposals of FROM (default: the same library). Run ids end in `-proposed`. `scenarios.get` finds proposed scenarios by id, so `check` and repros work on them. The checker's reference rule now looks for each scenario in every sweep of the other libraries, newest first.
- Model client (`trueup.model`): the `openai` SDK against `TRUEUP_MODEL_BASE_URL`. `claude-sonnet-4.6` for planning and fixing, `claude-haiku` for cheap jobs; opus models are refused. Retries with backoff on connection, timeout, 429 and 5xx errors. Invalid JSON is retried twice, then the worker stops with an error.
- Spending guard: before every model call, GET `<base without /v1>/key/info` and refuse if `info.spend` >= $15. Spend before and after, tokens and run cost are written to `spend.json` in the run dir.
- Trueup traces itself with neatlogs (`trueup.tracing`) for commands that call the model: `neatlogs.init` with the openai instrumentation and tags (run id, library, version, command). One run is one session (session id = run id). Workers run as root traces named `trueup-planner`, `trueup-runner`, `trueup-comparer`, `trueup-checker`, `trueup-deduper`, with `trueup.run_id`, `trueup.library` and `trueup.verdict`. Flushed in a `finally` and at exit, so a crash still flushes. Without `NEATLOGS_API_KEY` it says so once and runs untraced. Scenario subprocesses are unchanged: no neatlogs key, export off; an e2e test records every non-loopback connection a scenario child makes and expects none.
- `trueup doctor` reports whether neatlogs and the model proxy are reachable and the key's spend (one GET each, no model call), and whether `NEATLOGS_PROJECT` and `TRUEUP_MODEL_BASE_URL` are set.
- Dependencies: `openai` and `neatlogs` are now runtime dependencies.

- `trueup check <run_id|latest> [--library x]`: runs the checker and the deduper over a sweep's leads and writes `findings.json`, `withdrawn.json` and `evidence.json` next to `leads.json`. Prints findings by severity, withdrawn by rule and already-known. Exits 1 if there is a finding.
- Checker (`trueup.core.checker`): seven rules, each a pure function over recorded evidence: fresh process twice, recommended setup, latest release and main branch, fake truthful, harness sane, reference (another library or the OTel conventions), and a repro under 40 lines. A lead is a finding only if every rule passes; otherwise it is withdrawn with the rule that failed, kept as a lead, or marked "disputed semantics". Withdrawn leads are kept and counted.
- Evidence gathering (`trueup.check`): upgrades the library's venv to the latest release and records versions against PyPI, reruns each scenario twice, builds `.trueup/venvs/<lib>-main` from a shallow clone of the library's main branch, reads the other libraries' latest sweeps, and generates and runs a repro per scenario (`repros/` in the run dir). Leads are compared again with today's adapters.
- Grouping (`trueup.core.group`): leads with the same library, check, field and code path become one finding with a list of scenarios.
- Deduper (`trueup.dedupe`): searches the library's GitHub issues and PRs in all states with `gh search issues --include-prs`, lists the integration's titles, records each search with its date and marks a finding "already known" with the link when a title names the integration and the behaviour. Read only.
- Repro generator (`trueup.core.repro`): a short script that runs a scenario offline under a library and prints its leads.
- Deduper: title matches read by hand that do not cover a finding are kept as "related" with the reason; token findings ignore titles about reasoning tokens.
- Check results are cached per scenario in the run dir (`check-cache/`), so an interrupted check resumes.
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
