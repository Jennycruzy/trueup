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

## 2026-10-10: the planner, the model client and tracing Trueup with neatlogs

- `trueup plan <lib>` asks `claude-sonnet-4.6` for new scenarios as JSON and keeps only what code accepts: valid schema, an existing app, a fake behaviour that app's route supports, an app + model pair not yet covered, and expected truth that an untraced run confirms. Rejected proposals go back to the model with the reason, twice at most. Accepted ones are in `scenarios/proposed/<lib>/` and run with `trueup sweep <lib> --proposed [FROM]`.
- Spending guard: the key's spend is read from the proxy before every call; at $15 Trueup stops.
- Trueup's own run is traced to neatlogs: one session per run, one trace per worker. The scenario subprocesses still get no neatlogs key and have export off; an e2e test watches every outgoing connection from a scenario child and sees none.

### Real runs

`trueup plan openllmetry --max 3` (neatlogs session `20261010T234842Z-plan-openllmetry`) and `trueup plan neatlogs --max 3` (session `20261010T235208Z-plan-neatlogs`). The session id is the run id.

| run | proposals | accepted | rejected | model calls | tokens in / out |
|---|---|---|---|---|---|
| openllmetry | 3 | 3 (all after 1-2 revisions) | 0 | 5 | 29,329 / 1,729 |
| neatlogs | 3 | 3 (2 after revisions) | 0 | 4 | 30,972 / 1,529 |

No proposal was finally rejected, but 6 of 9 tries were rejected first. Reasons: `expected.exception` missing when outcome is exception (4; my first prompt told the model to leave out fields when unsure, and it was not told this one is required), wrong exception class (3: guessed `APIStatusError` or `APIConnectionError`; the untraced run gave `BadRequestError`, `APIConnectionError` and `RemoteProtocolError`), and wrong fake outcome (1: guessed `error_event`; the fake answered HTTP 400 because the app does not stream).

Cost: the per-run spend deltas were $0.0909 and $0.1000. The key's total spend after both runs is $0.2528. The extra $0.06 showed up between and after the runs, when Trueup made no model call, so the proxy's spend figure lags. Tokens at Sonnet list prices ($3 / $15 per million) come to about $0.23, which matches the total. The per-run `run_cost_usd` in `spend.json` reads low for this reason.

Two problems in the planner's output, both fixed:
- `p-an-async-stream-error` said "async anthropic stream", but `an_async_create` does not stream; with the error-event fake model the fake answers HTTP 400. The truth was right (the untraced run confirmed it); only the prose was wrong. Code cannot check prose. I corrected its `does` by hand (the file says so), and the prompt now gives each app's real description. The neatlogs run's descriptions were accurate.
- `p-oa-chat-async-stream-error` caused a false "library changed the request" note: the proposal had `tokens: [null]` and no `include_usage`, so the comparer assumed the app did not ask for usage. The planner now copies `include_usage` from the untraced run (no library there) into accepted chat proposals.

Accepted scenarios: openllmetry `p-an-async-stream-error`, `p-an-stream-helper-error-event`, `p-oa-chat-async-stream-error`; neatlogs `p-an-async-stream-cut`, `p-an-stream-helper-cut`, `p-lc-tools`.

### Leads and findings from them

Each set of proposals was swept under all three libraries, so the checker's reference rule had another library to compare against. OpenInference recorded all 6 correctly.

| sweep | leads | checked findings |
|---|---|---|
| openllmetry, its proposals (`20261010T235010Z-openllmetry-proposed`) | 3 | 3 (2 high, 1 medium) |
| neatlogs, openllmetry's proposals (`20261010T235028Z-neatlogs-proposed`) | 2 | 2 (1 high, 1 medium) |
| neatlogs, its proposals (`20261010T235240Z-neatlogs-proposed`) | 2 | 2 (1 high, 1 medium) |
| openllmetry, neatlogs' proposals (`20261010T235247Z-openllmetry-proposed`) | 1 | 1 (high) |
| openinference, both sets | 0 | - |

Every lead passed all seven rules (reproduced twice, latest release and main, repro). Nothing was withdrawn. The deduper found no matching issue or PR.

- neatlogs, new: when a `messages.stream()` stream fails (error event, or a cut connection) the span is OK, with no exception event (HIGH run status, MEDIUM call status; one finding each in two runs). Earlier sweeps only covered failures through `messages.create(stream=True)`, which neatlogs records right. The known `messages.stream()` gaps (PR 180: no tokens, text, finish) are about successful streams; whether PR 180 also fixes this was not checked.
- openllmetry: no span at all when a `messages.stream()` stream fails (error event, cut). The async chat stream that gets an error event ends OK with no exception event. These look like the same causes as the earlier findings (no span for Anthropic `create(stream=True)` errors; chat streams that raised end OK) reached through other code paths: the stream helper and the async client. I count them as more evidence for known findings, not new bugs, until the code says otherwise.
- `p-an-async-stream-error`, `p-an-async-stream-cut` and `p-lc-tools` gave no lead in any library.

So the planner found one new neatlogs behaviour (`messages.stream()` failures show OK) and widened two openllmetry findings to new code paths. All 6 accepted proposals were near variations on existing ones: failure fake models paired with a different app.

## 2026-10-11: the fixer, the verifier, and three real fixes

- `trueup fix <finding-id>`: locate, patch, verify, up to 3 tries per run; `trueup upstream <finding-id>` drafts issue and PR text. Every run is traced in neatlogs as `trueup-fixer` and `trueup-verifier` (session id = run id). Nothing was committed, pushed or posted anywhere.
- Entire's code graph was not used. `entire agent-help` (CLI 0.11.4) lists no graph command; `entire graph` answers "the entire-graph plugin is not installed", and `agent-help` lists `entire plugin` as the user's command, so Trueup did not install it. Locate used ripgrep plus Python's ast. Each `locate.json` records the Entire commands, their output and this reason.
- Model: `claude-sonnet-4.6`; the $15 guard stayed on. Key spend went from $0.2528 to $5.9869 ($5.73) over 11 fix runs. The per-run deltas add up to $5.42; the proxy's spend lags, as seen with the planner.

### Fix runs, every try

OpenLLMetry, `openllmetry-call_count-openai-agents-llm-spans-wrong` (Agents SDK non-streamed runs record two LLM spans per call):

| run | try | result | why |
|---|---|---|---|
| 000319Z | - | stopped, $0 | one test venv for both packages: their pytest-asyncio pins conflict. Now one venv per package. |
| 000336Z ($0.66) | 1 | fail: scenarios | set `SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY` in the Agents span context, but the Responses wrapper only checks `_SUPPRESS_INSTRUMENTATION_KEY`; still 4 spans for 2 calls. Its test only checked that the key was set. |
| | 2, 3 | fail: apply | my bug: the clone was not reset after try 1, so the edits were checked against try 1's files. Also the excerpt of a long file had line-number prefixes and no imports, so the model guessed an import block. |
| 001405Z ($0.59) | 1 | fail: own test | right idea (set the key, check it in the wrapper); one of its new tests failed |
| | 2, 3 | fail: apply | same reset bug. Fixed: the clone is reset before each draft; excerpts are verbatim with the imports; a missing `old` text gets the nearest real lines back. |
| 001706Z ($0.27) | 1 | pass, then withdrawn | passed every check at the time. Later I found the verifier left the new test out of the suite comparison: one new async test (`asyncio.get_event_loop()`) passed alone and failed inside the suite. Rule fixed; this result does not count. |
| 010426Z ($0.65) | 1 | fail: scenarios | patched only the Agents side; the feedback now carries the scenario's truth vs trace and the spans |
| | 2 | fail: suite | a new async test failed inside the full suite (counted now) |
| | 3 | **pass** | |

OpenInference, `openinference-run_status-openai-agents-top-level-span-status-ok` (a crashed Agents SDK run shows OK at the top-level span):

| run | try | result | why |
|---|---|---|---|
| 002549Z ($0.59) | 1 | fail: own test | the test's agent never reached the error it wanted |
| | 2 | fail: full library | any ERROR child marked the root ERROR: `ag-tool-raises` (tool raised, run recovered) became ERROR. The full-library check caught it. |
| | 3 | fail: scenarios | only agent-span errors counted; `ag-bad-tool` and `ag-streamed-error` carry the error on a `turn` or `response` span |
| 003256Z ($0.68) | 1 | fail: own test | |
| | 2, 3 | fail: scenarios | counted only spans whose parent is the trace root; the agent span sits under an SDK "Agent workflow" span. The prompt now includes the spans each scenario exported before the patch. |
| 003533Z ($0.73) | 1 | fail: own test | |
| | 2 | fail: full library | `ag-tool-raises` ERROR again |
| | 3 | fail: scenarios | `ag-bad-tool`, `ag-streamed-error` again. Part of the cause was my note in `targets.py`, which said the SDK puts the error on the agent span; the data says otherwise. The note now says the span differs by failure. Failing scenarios now also return the spans the patched library exported. |
| 004013Z ($0.63) | 1, 2 | fail: own test | |
| | 3 | **pass** | any ERROR on a span that is not a function (tool) span marks the root ERROR |

neatlogs, `neatlogs-run_status-anthropic-messages-stream-top-level-span-status-ok` (a failed `messages.stream()` shows OK; scenarios from both planner runs merged):

| run | try | result | why |
|---|---|---|---|
| 004502Z ($0.22) | 1 | pass, then withdrawn | the package's suite did not run at all (one module needs `google.genai`; collection stopped: 0 passed, 1 error) and the verifier read "same failures as before" as a pass. Fixed: pytest runs with `--continue-on-collection-errors`, and a baseline suite with nothing passing stops the fixer before any model call. This result does not count. |
| 005144Z ($0.40) | 1 | **pass** | the stream manager wrappers pass the exception to `_finalize`, which calls the existing `_err` (ERROR, exception event, end) |

### Results

| finding | scenario before → after | package suite before → after | full library leads (high) before → after | new mismatches |
|---|---|---|---|---|
| OpenLLMetry double LLM spans | ag-run 4 → 2 spans (truth 2); ag-max-turns 6 → 3; ag-bad-tool 2 → 1; ag-llm-fails, ag-tool-raises 4 → 2 | openai-agents 405 passed, 1 failing → 409 passed, same 1 failing (`test_none_finish_reason_omits_attribute`, fails on the clean clone too); openai 291 passed, 1 skipped → same | 32 (22) → 27 (17) | 0 |
| OpenInference root OK on failed run | 5 scenarios OK → ERROR (truth ERROR) | 295 passed → 298 passed | 19 (7) → 14 (2) | 0 |
| neatlogs `messages.stream()` failure OK | p-an-stream-helper-cut, p-an-stream-helper-error-event OK → ERROR | 527 passed, 1 collection error (`google.genai` not installed), 4 skipped → 530 passed, same error | 35 (11) → 31 (9) | 0 |

Full library = 57 scenarios (51 + 6 planner proposals) in a venv with the library's packages built from the clone, before and after the patch. Clone commits: OpenLLMetry `df4921a409`, OpenInference `c364180e5b`, neatlogs `202f8776ea`.

The standalone repros (`upstream/<id>/repro.py`, 27-30 lines, only the library and the SDK, `httpx.MockTransport`), on the latest release and then on the patched clone:
- OpenLLMetry: "LLM spans: 2; output tokens 14 (provider sent 7)" → "LLM spans: 1; output tokens 7".
- OpenInference: HTTP 500, the run raises `InternalServerError`; top-level span OK → ERROR.
- neatlogs: SSE stream ending in an error event, the app sees `APIStatusError`; span OK, 0 exception events → ERROR, 1 exception event. anthropic 1.13 uses `httpx2`, so this repro imports `httpx2`.

Limits, read by hand:
- Several new tests contain functions that also pass without the patch (OpenLLMetry 3 of 4, OpenInference 2 of 3, neatlogs 1 of 3). The OpenInference and neatlogs ones are "stays OK when the run succeeds" guards. The OpenLLMetry wrapper tests feed a MagicMock response; the unpatched wrapper fails inside `@dont_throw` and exports nothing, so they would pass either way. Each fix rests on the test functions that do fail before, plus the real scenarios and the repro. The verifier now lists such test functions in every log.
- OpenInference: any ERROR on a span that is not a tool span marks the run ERROR. A span error the SDK later recovers from (none in the scenarios) would also mark the root ERROR.
- neatlogs: on failure the span gets the error and ends; partial text and tokens from before the failure are not recorded.
- The OpenLLMetry openai-agents test suite itself tries to upload Agents SDK traces with its fake key (it prints "Tracing client error 401"). No real key is in the test environment: `vf.test_env()` drops every variable whose name has KEY, TOKEN, SECRET or PASSWORD.
- Three verifier holes were found during these runs and closed (clone not reset between tries; new tests left out of the suite comparison; a suite that does not run read as "same failures"). Two "passes" were withdrawn because of them. Earlier tries in these logs ran under the weaker rules.

Upstream drafts are in `upstream/<id>/` (issue.md, pr.md, repro.py, repro-output.json). None was posted.

## 2026-10-11: locate with Entire's code graph

- The entire-graph plugin is now installed. I read `entire graph agent-guide` and `entire graph capabilities --json` (schema 1.1; Python is a semantic language with CALLS, ASYNC_CALLS, INHERITS, OVERRIDES and type relations; no feature needs the network).
- Locate now uses the graph first, as the guide says. It checks capabilities, then per target package runs one `entire graph search --profile full` with the finding as a sentence ("openai-agents tracing: LLM spans is 4 in the span but really 2 ..."). For the top 3 hits it runs `entire graph neighbors --relation CALLS --direction in` (callers) and `entire graph impact`. The library's own reference pattern comes from a second search. Test files are dropped from the hits. ripgrep + ast on the hand-written seed symbols is only the fallback: when the graph is missing, has no Python support, fails or finds no function. locate.json says which was used and why.
- `trueup fix <id> --locate-only` re-runs only this step (no model call, no patch). It writes `locate.json` with every graph command and its JSON output, and keeps the locate output the fix runs used as `locate-fix-run.json`. It also writes `graph-compare.json/.md`: each function the verified `patch.diff` changed (found from the diff's lines with ast) and where it ranks in the graph's hits and in the fallback's.
- Paths: the graph prints `repo_root` as an absolute path. Every file Trueup writes under `fixes/` and `upstream/` now goes through `locate.save`, which makes this machine's paths relative (clone paths relative to the clone, `~` for home). The committed files had no absolute paths to remove.

Did the graph point at the function that was actually patched? Ranks among the graph's search hits (8 per package):

| finding | patched functions | graph found | in graph top 3 | ranked 1st | notes |
|---|---|---|---|---|---|
| OpenInference root span OK | `on_span_end`, `on_trace_end`, `__init__` | 2 of 3 | `on_span_end` at 2 | no (`_get_span_status` was 1st) | `on_trace_end`, which sets the root status, ranked 6; `__init__` only gains a dict |
| OpenLLMetry double LLM spans | `on_span_start`, `on_span_end`, `__init__` (agents), sync and async `responses_get_or_create_wrapper` (openai) | 1 of 5 | none | no | `responses_get_or_create_wrapper` at 6. The top hits were the realtime span code. `on_span_start` appeared only as a caller (`neighbors`) of hit 3, `_start_agent_span` |
| neatlogs `messages.stream()` failure OK | `__exit__`/`__aexit__` and `_finalize` of both stream manager wrappers | 0 of 4 | none | no | the top 2 were `_finalize_error` of the shared stream wrappers in `_wrap_utils.py`: the same kind of code (error on a stream), in a different place |

So for the three fixes the graph pointed at the patched function in one case (OpenInference, rank 2), was close in one (OpenLLMetry, the openai half at rank 6) and missed in one (neatlogs). The fallback's "rank" is not a fair comparison. It searches seed symbols that I wrote into `targets.py` after reading the code, and for neatlogs it only returns the classes. The fix runs themselves used the fallback, and the model was given whole files around those definitions. Whether graph-only locate would have led to the same patches was not tested: that needs new model calls.
