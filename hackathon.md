# Build log

neatHack, 10-12 Oct 2026.

## 2026-10-10: skeleton

- Set up the uv project (Python 3.12, src layout) with the `trueup` command.
- Added the data model in `trueup.core`: Observation, Mismatch, Run, Finding and Severity, each with `to_dict`/`from_dict`.
- `trueup doctor` reports the Python version and whether the two keys are set, without printing them. Other commands exit 2 with "not built yet".
- Tests for the round trip, severity order and doctor. CI runs them on push.
- Nothing is audited yet. No findings so far.

## 2026-10-10: the truth side

- `trueup.fake`: a local fake provider (stdlib http.server in a thread, random free port). It speaks OpenAI Chat Completions, OpenAI Responses and Anthropic Messages. The request's model name picks the scenario: plain, streamed with and without usage, two parallel tool calls with split streamed arguments, refusal, n=2, HTTP 500 and 529, error event mid-stream, status failed and incomplete, reasoning summary, thinking, tool_use with input_json_delta, and a dropped connection. Every id is unique per call and per fake instance. The truth log records each request and what was sent back, including tokens per call, or that no usage was sent.
- 34 fixture tests run the real `openai` and `anthropic` SDKs against the fake. Two SDK behaviours we found and recorded: the openai SDK passes a Responses `error` event to the app instead of raising, and the anthropic SDK lets a dropped stream through as a raw `RemoteProtocolError`, not an SDK exception.
- `trueup.scenarios`: 31 plain-SDK scenarios as data (chat 12, Responses 9, Anthropic 10), each with expected truth. A unit test runs every app with no tracing library and checks the expectations against what really happens. That check caught one wrong expectation (streamed tool calls without include_usage carry no tokens). 20 LangChain/LangGraph/OpenAI Agents cases are listed as not_built.
- `trueup.runner`: runs one scenario in a fresh subprocess in `.trueup/venvs/<lib>` (built with uv), using the library's recommended setup and an in-memory span exporter. It returns truth plus spans as JSON. A scenario that cannot run is reported NOT RUN with the reason.
- Regression tests for four traps: reused response ids, a reused async client across asyncio.run, a missing-usage reply read as a bug, and neatlogs exporting to a dead endpoint.
- `trueup sweep <library>` writes observations and `summary.txt` to `.trueup/runs/<run_id>/`. All three libraries ran 31/31. The first openllmetry sweep was 0/31 NOT RUN because `traceloop-sdk` imports `httpx` without declaring it; we now install `httpx` in that venv.
- Leads for the comparer (not judged yet): neatlogs adds `stream_options.include_usage` to the app's streamed chat request. openinference exports no span for a stream closed early, or for a Responses stream that ends with an error event. openllmetry marks chat streams that raised (error event, cut) as OK, and exports no span for Responses failed/incomplete or for Anthropic stream errors and cuts.

## 2026-10-10: the comparer and the reports

- `trueup.core.compare` checks truth against the spans: run status, call status, call count, span closed, tokens, output (text, refusal, tool calls with arguments compared as JSON), finish, plus a "request changed" note. Severity: HIGH changes a number or status a dashboard shows by default, MEDIUM is wrong or missing span detail, LOW is extra or cosmetic.
- `trueup.core.adapters`: one data-driven adapter per library saying where it keeps tokens, finish reasons, outputs and response ids. Tested against span JSON from the sweeps, saved in `tests/fixtures/spans/` with stack traces and local URLs removed. OpenLLMetry error spans for failed Responses streams have no `gen_ai.operation.name`, so its adapter keys on `gen_ai.provider.name`.
- Choices made while comparing: finish reasons are compared through a synonym table (end_turn = stop, tool_use = tool_calls = tool_call, incomplete = length), because OpenLLMetry normalises them; a completed Responses call that asked for a tool may show `tool_call`. When the app closes a stream early, output, tokens and finish are not compared, since the app never got them. Tokens are only compared when the fake sent usage. Spans are matched to calls by response id, then by start order.
- A mismatch is called a lead. `trueup sweep <lib>` now prints a leads table, writes `leads.json` and exits 1 if there is any lead.
- `trueup audit <agent.py> --library <lib>` runs the script's `main()` against the fake, once per fake scenario on each route the script calls, and compares. Limits are written in `src/trueup/audit.py`. Tried on `examples/agent.py` under openinference: 8 runs, 1 lead (refusal not recorded).

Sweeps after the comparer (31/31 ran for each library). These are leads, not confirmed bugs; the self-check comes next.

| library | leads | high | medium | low | notes |
|---|---|---|---|---|---|
| neatlogs | 22 | 4 | 18 | 0 | 5 |
| openinference | 10 | 2 | 8 | 0 | 0 |
| openllmetry | 14 | 11 | 3 | 0 | 0 |

Leads per check:

| check | neatlogs | openinference | openllmetry |
|---|---|---|---|
| run_status | 1 | 0 | 3 |
| call_status | 1 | 0 | 3 |
| call_count | 0 | 0 | 0 |
| span_closed | 0 | 2 | 4 |
| tokens | 3 | 0 | 4 |
| output | 7 | 1 | 0 |
| finish | 10 | 7 | 0 |

- neatlogs: Anthropic `messages.stream` spans carry no tokens, text, tool calls or finish reason (3 scenarios); Responses spans carry no status/finish (7) and no function calls (2); the chat refusal is not recorded; the Responses stream that ends with an error event stays UNSET with no exception event. The 5 notes are neatlogs adding `stream_options.include_usage` to streamed chat requests; tokens were compared against what the fake really sent.
- openinference: no span for a chat stream closed early or for a Responses stream ending in an error event; Responses spans carry no status/finish (7); the chat refusal is not recorded.
- openllmetry: chat streams that raised (error event, cut) and the Responses error-event stream end OK; no span for Responses failed/incomplete or for Anthropic stream error/cut; Anthropic streamed spans record 4 output tokens where the provider sent 3 (4 scenarios).

## 2026-10-10: framework scenarios

- The fake now runs agent flows. It picks each reply from the request, so it keeps no state: no tool result yet means a tool call, a tool result means the answer. Chat Completions: one tool, two parallel tools, a loop that always asks for the tool, and HTTP 500 on the second call. Responses (for the OpenAI Agents SDK): one tool, a loop, 500 on the second call, a tool name the agent does not have, and an error event or a dropped connection in the streamed answer, after the full streamed event sequence of the first call. Fixture tests run them through the real openai SDK, LangChain, LangGraph and the Agents SDK.
- 20 framework scenarios are built: LangChain 6, LangGraph 6, OpenAI Agents SDK 8. Each has expected truth, including which tools really ran and which raised. The untraced check runs all 51 scenarios with the real SDKs. Two things it showed: LangGraph's `create_react_agent` does not raise at the step limit (it answers "Sorry, need more steps"), and langchain-openai raises its own `OpenAIAPIError` and `OpenAIConnectionError`.
- Setups per framework. neatlogs: `neatlogs.init(instrumentations=[...])` with its README keys (`langchain`, `langchain`+`langgraph`, `openai_agents`), export off. OpenInference: `LangChainInstrumentor` or `OpenAIAgentsInstrumentor`, and the OpenAI/Anthropic ones only for plain SDK runs. OpenLLMetry: `Traceloop.init(exporter=<in-memory>, disable_batch=True)` for everything. The Agents SDK's own uploader to api.openai.com is removed; the instrumentors' processors stay. Each agent gets its own AsyncOpenAI client.
- Trap found: the first neatlogs LangChain run exported no spans and raised no error. neatlogs checks `import langchain`, and the venv had `langchain-core` and `langchain-openai` but not `langchain`, so it logged "Skipped: langchain (not installed)". Every venv now installs `langchain`. Before a framework scenario runs, the runner checks that the framework imports and that an instrumentor for it is active, and reports NOT RUN with the reason if not. A regression test covers this.
- Comparer: run status uses the trace root (for the Agents SDK, "Agent workflow"). Two new checks. `tools`: every tool that really ran has a tool span, and a tool that raised has an ERROR span or an exception event. `error_recorded`: when the app raised but no provider call failed (unknown tool, max turns), some span must record an error. The OpenLLMetry adapter no longer counts LangGraph task, tool, agent and workflow spans as LLM calls. A scenario can say the app itself asked for stream usage, so LangChain's `stream_usage=True` is not reported as the library changing the request.

Sweeps with all 51 scenarios (runs `20261010T203332Z-neatlogs`, `20261010T203600Z-openinference`, `20261010T203755Z-openllmetry`). 51/51 ran for each library; nothing NOT RUN. The plain-SDK counts are unchanged from the last sweep. These are leads, not confirmed bugs.

| library | leads | high | medium | low | notes | of which framework |
|---|---|---|---|---|---|---|
| neatlogs | 58 | 9 | 49 | 0 | 5 | 36 (high 5, medium 31) |
| openinference | 19 | 7 | 12 | 0 | 0 | 9 (high 5, medium 4) |
| openllmetry | 29 | 21 | 8 | 0 | 0 | 15 (high 10, medium 5) |

Leads per check (all scenarios; framework scenarios in brackets):

| check | neatlogs | openinference | openllmetry |
|---|---|---|---|
| run_status | 6 (5) | 5 (5) | 8 (5) |
| call_status | 4 (3) | 3 (3) | 6 (3) |
| call_count | 0 | 0 | 5 (5) |
| span_closed | 0 | 2 (0) | 4 (0) |
| tokens | 3 (0) | 0 | 4 (0) |
| output | 8 (1) | 2 (1) | 1 (1) |
| finish | 37 (27) | 7 (0) | 0 |
| tools | 0 | 0 | 0 |
| error_recorded | 0 | 0 | 1 (1) |

- All three: when an Agents SDK run raises (500 on the second call, max turns, unknown tool, streamed error event, streamed cut), the root "Agent workflow" span is OK (5 scenarios each). For the provider failures the inner `response` span is ERROR but has no exception event (3 each). The LangChain refusal is not recorded as output (1 each). Tool spans were right everywhere, including the raised tool.
- neatlogs: framework LLM spans have no `neatlogs.llm.finish_reason` (27). The OpenInference `llm.finish_reason` is on the same span; the adapter reads the neatlogs namespace only, as in the plain-SDK sweeps.
- openllmetry: in non-streamed Agents SDK runs every model call gets two LLM spans, one from the Agents SDK instrumentation and one from the OpenAI instrumentation under it. That doubles calls and tokens (ag-run: 2 calls and 36 tokens really; 4 spans and 72 tokens in the trace). Streamed runs get one span per call. The unknown-tool error is on no span: `no_such_tool` only appears as the tool call in the model's output.

Answers to the three questions:
1. Does a crashed Agents SDK run show OK at the top level? Yes, in all three libraries, in all 5 crash scenarios.
2. Does OpenLLMetry with Traceloop.init double LLM calls and tokens for the Agents SDK? Yes in non-streamed runs (5 of 5 scenarios, exactly 2x). Streamed runs are not affected (3 of 3 have one span per call and the right tokens).
3. Does an unknown-tool error appear anywhere in the trace? neatlogs and OpenInference: only as the status description of the `turn` span (ERROR, no exception event); the root stays OK. OpenLLMetry: nowhere.

## 2026-10-10: the checker and the deduper

- `trueup check <run_id|latest> --library <lib>` takes a sweep's leads through seven rules: reproduces twice in fresh processes; recommended setup with the framework installed; latest release (checked against PyPI) and the library's main branch (shallow clone, installed into `.trueup/venvs/<lib>-main`); the fake sent what truth claims; harness sane (own client per event loop, export off, no endpoint); another library or the OTel conventions show the right behaviour; a repro under 40 lines reproduces it. A lead that passes every rule is a finding; otherwise it is withdrawn with the failing rule, kept as a lead, or marked "disputed semantics". Withdrawn leads stay in `withdrawn.json`.
- Findings with the same library, check, field and code path are grouped into one finding with a list of scenarios.
- The deduper searches each library's issues and PRs (all states, `gh search issues --include-prs`), lists the integration's titles and records each search with its date (in `findings.json`). Read only: nothing was opened, commented on or posted.
- Repros are generated per scenario in `.trueup/runs/<run>/repros/` (31 lines each). They run offline with fake keys, but they import trueup for the fake provider and the app code, so they are not yet standalone scripts for an upstream issue.

### Trueup's own false alarm: neatlogs finish reason

The neatlogs adapter read the finish reason only from `neatlogs.llm.finish_reason` / `neatlogs.llm.choices.N.finish_reason`. In the real spans from run `20261010T203332Z-neatlogs`, every framework LLM span (LangChain, LangGraph, Agents SDK) comes from an OpenInference instrumentor (scope `openinference.instrumentation.langchain` / `.openai_agents`). These spans carry the right finish reason in `llm.finish_reason`. neatlogs copies tokens and tool calls into its own namespace but not the finish reason. The finish reason is in the exported trace, so the leads were ours. The adapter now also reads `llm.finish_reason`.

Same saved run, compared again: 58 leads before, 31 after. All 27 removed leads were `finish` leads on framework scenarios: ag-bad-tool 1, ag-llm-fails 1, ag-max-turns 3, ag-run 2, ag-streamed 2, ag-streamed-cut 1, ag-streamed-error 1, ag-tool-raises 2, lc-invoke 1, lc-refusal 1, lc-stream 1, lg-agent 2, lg-llm-fails 1, lg-parallel 2, lg-step-limit 3, lg-stream 2, lg-tool-raises 1. The 10 plain-SDK finish leads stay. Whether the neatlogs dashboard shows `llm.finish_reason` was not checked.

### Results

Checked against the latest releases (neatlogs 1.4.26; OpenInference openai 0.1.65, anthropic 3.0.3, langchain 0.1.79, openai-agents 2.5.3; OpenLLMetry 0.62.4, all equal to PyPI) and main (neatlogs `202f8776ea`, openinference `c364180e5b`, openllmetry `df4921a409`). Every main branch installed.

| library | leads | finding leads | findings (grouped) | high | medium | withdrawn | disputed | already known |
|---|---|---|---|---|---|---|---|---|
| neatlogs | 31 | 27 | 12 | 3 | 9 | 0 | 2 groups (4 leads) | 3 |
| openinference | 19 | 15 | 6 | 3 | 3 | 0 | 2 groups (4 leads) | 0 |
| openllmetry | 29 | 23 | 9 | 6 | 3 | 2 (latest_and_main) | 2 groups (4 leads) | 1 |

Withdrawn: openllmetry, oa-resp-failed and oa-resp-incomplete (no span for a Responses call with status failed or incomplete). Both reproduce on 0.62.4 but not on main, so they are fixed there.

Disputed semantics, in all three libraries: (1) on Agents SDK provider failures the `response` span is ERROR but has no exception event (ag-llm-fails, ag-streamed-error, ag-streamed-cut); the conventions require the status, not the event. (2) the LangChain refusal is not recorded as output (lc-refusal); the GenAI conventions have no refusal part and no library records it.

neatlogs findings:
- HIGH: Agents SDK run that raises (5 scenarios): root "Agent workflow" span is OK.
- HIGH: Responses stream ending in an error event: top-level span stays UNSET (and, MEDIUM, the call span has no exception event).
- HIGH: `messages.stream()` (3): no tokens on the span. MEDIUM, same scenarios: no finish reason, no output text, no tool call.
- MEDIUM: Responses create (5) and stream (2): no status/finish reason. Responses create and stream: function calls not recorded.
- MEDIUM: chat refusal not recorded.
- Already known: the `messages.stream()` output finding matches open PR https://github.com/neatlogs/neatlogs/pull/180 (issue https://github.com/neatlogs/neatlogs/issues/179). Both Responses tool-call findings match open PR https://github.com/neatlogs/neatlogs/pull/186 (issue https://github.com/neatlogs/neatlogs/issues/185). From its description, PR 180 also covers the `messages.stream()` tokens, finish and tool-call findings (same cause), but the automated title match only marked the output one.

OpenInference findings:
- HIGH: Agents SDK run that raises (5): root span OK.
- HIGH: no span for a chat stream the app closes early, or for a Responses stream ending in an error event.
- MEDIUM: Responses create (5) and stream (2): no status/finish reason.
- MEDIUM: chat refusal not recorded. Not known: the title matcher hit PR 3996, PR 3797 and issue 3785. Read by hand, they are about streamed refusal fragments being overwritten, not a non-streamed refusal going missing. They are recorded as "related".

OpenLLMetry findings:
- HIGH: Agents SDK non-streamed runs (5): two LLM spans per model call (Agents SDK and OpenAI instrumentations), doubling calls and tokens.
- HIGH: Agents SDK run that raises (5): root span OK.
- HIGH: chat streams that raised (error event, cut) and the Responses error-event stream: top-level span OK; MEDIUM, the call span is OK with no exception event.
- HIGH: no span for an Anthropic stream that errors or drops mid-stream (2).
- HIGH: streamed Anthropic spans record 4 output tokens where the provider sent 3 (4). Already known: open PR https://github.com/traceloop/openllmetry/pull/4377 describes this exact double count (`message_start` added to the running total in `message_delta`).
- MEDIUM: unknown tool name in an Agents SDK run is on no span.
- Title matches read by hand and rejected: issue 4536 (spans not ended when the app stops reading early; ours is no span after an error or cut), and PRs 4461 and 4462 (reasoning tokens). Token findings now ignore titles about reasoning tokens.

Limits: rule 6 passed for most findings because another library got the same scenario right. Three groups, the Agents SDK root status in each library, rely on the OTel status rule instead, since all three libraries get it wrong. The title matcher in the deduper made 9 matches; 5 were wrong when read by hand; every "already known" above was read by hand.
