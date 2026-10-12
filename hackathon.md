# Build log

neatHack, 10-12 Oct 2026.

## 2026-10-12: findings became Neatlogs detections

- OBSERVED: added an idempotent three-rule conditional pack and two trace-level code detections. Each live conditional rule
  was previewed before creation; their 30-day trends are 25, 25, and 6 occurrences.
- OBSERVED: added an explicit fake-only demo exporter with a 30-span ceiling. Neatlogs and OpenInference each persisted three
  queryable demo traces. OpenLLMetry delivered its spans but Neatlogs did not group them under the requested session;
  that limitation is recorded instead of counted as a successful demo.
- OBSERVED: model spend was unchanged; this milestone made no model calls.

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

## 2026-10-11: v2 from v1's traces, the evidence bundle and the judge path

### Reading v1's traces back from neatlogs

- Public API (`app.neatlogs.com/api/v1/public`): every call with `NEATLOGS_API_KEY` answers 401 "A valid public API credential is required", with `x-api-key` or `Bearer`, with or without `x-project-id`. The docs say "Ingest credentials do not authorize Public API reads"; reads need a public API key or a service-account token, and we have neither. The docs do not say whether it is paid-only.
- MCP server (`ingest.neatlogs.com/mcp`): it accepts the project key as a bearer token. `trueup traces <session-id>` (`trueup.neatlogs_read`) uses only `search_traces` and `get_trace_context`. Three limits: field projection on both answers `not_enabled` (NL-1923, NL-1924 rollouts), `get_trace_context(created_after=...)` answers HTTP 409, and search finds a trace only by keyword. Search is the only way to list traces.
- Search found 9 traces from v1's 12 model runs, against about 8 opened per fix run. Session `20261010T235208Z-plan-neatlogs` has none. So most of v1 had to be read from its local run records (`plan.json`, `fixes/*/runs/*.json`, `spend.json`). The traces still showed what the records could not: the model's reply text.

What v1 wasted, and the v2 change for each:

| waste in v1 | seen in | v2 change |
|---|---|---|
| Fixer replies that were not JSON, each retried with the full ~25k-token prompt: 14 of 40 fixer calls. The trace shows a reply that opens "Let me look more carefully at the exact import text...". | trace of `20261011T000336Z-fix-openllmetry`; calls vs tries in every fix run | lenient JSON (the first JSON object in the reply) and "the first character of your reply is {" |
| Revisions re-sent every earlier draft: 140,607 input tokens over 6 calls. | `20261011T003256Z-fix-openinference`; trace `20261011T002549Z` (48,598 tokens over 2 calls) | send the first prompt, the last draft and one line per earlier failure |
| A test failing after the patch was reported as the last 1,200 characters of pytest output, often warnings and captured logs. | `20261011T001405Z-fix-openllmetry` try 1 ("PydanticDeprecatedSince20..."), `20261011T004013Z-fix-openinference` try 1 ("Captured log call") | send the `E` lines, the failing test's location and the FAILED summary |
| Planner first tries guessed what the fake does: 3 wrong exception classes, 1 wrong fake outcome. | trace `20261010T234842Z-plan-openllmetry`; `plan.json` of `20261010T235208Z-plan-neatlogs` | the prompt lists what really happened in every existing scenario (app, fake model, fake outcome, exception) |
| Traces missing in neatlogs. | the 9 traces above | flush after each worker trace |

v1 = the planner and fixer as they were at the start of this session (the planner prompt already had the corrections from its first runs). Both versions ran today from the same code with `--variant v1|v2`. They are tagged `variant:v1` / `variant:v2` in neatlogs (and `trueup.variant` on every worker trace). Planner: `--max 3` on openllmetry and neatlogs. Fixer: the OpenInference root-status finding, which took 3 tries in all four earlier runs. The answer key now has 26 checked findings for openllmetry (9) and neatlogs (17). Recall is the share of them hit by a lead from the run's accepted proposals, swept under that library.

| job | version | sessions (= run ids) | first try accepted | tries per item | model calls (JSON retries) | tokens in / out | cost at list price | wall time | answer-key recall | traces found in neatlogs |
|---|---|---|---|---|---|---|---|---|---|---|
| planner | v1 | `20261011T013638Z-plan-openllmetry`, `20261011T013725Z-plan-neatlogs` | 2 of 6 | 1.83 | 7 (0) | 57,686 / 2,671 | $0.21 | 42 s | 5 of 26 | 0 of 2 |
| planner | v2 | `20261011T013704Z-plan-openllmetry`, `20261011T013748Z-plan-neatlogs` | 3 of 6 | 1.67 | 6 (0) | 59,681 / 2,281 | $0.21 | 40 s | 5 of 26 | 0 of 2 |
| fixer | v1 | `20261011T013927Z-fix-openinference` | 0 of 1 | 2 | 4 (2) | 108,886 / 13,389 | $0.53 | 253 s | fixed | 1 of 6 |
| fixer | v2 | `20261011T014344Z-fix-openinference` | 0 of 1 | 2 | 2 (0) | 49,438 / 4,900 | $0.22 | 334 s | fixed | 1 of 6 |

What this shows:
- Fixer: v2 used half the calls, 55% fewer input tokens and 58% less money for the same result (fixed on try 2). The saving is the two JSON retries plus the shorter revision prompt. v2 took longer: its try 1 got further (it failed at the full scenario library, not at the finding's scenarios), so more verifier time. One run each, so try counts are not a measured improvement.
- Planner: v2 accepted one more proposal on the first try (3 of 6 against 2 of 6) at the same cost. That is one proposal in a sample of six, so it is not evidence that v2 is better. v2 also accepted a bad scenario: `p-an-async-stream-tools` pairs a non-streaming app with a streaming fake model, and the app then crashes with its own `AttributeError`. The untraced run agreed with the stated truth, so code accepted it. v1 accepted no such scenario.
- The per-worker flush did not help. neatlogs search finds none of the four planner sessions and one trace per fix session, for v1 and v2 alike. Whether the traces were never stored or only not indexed for search could not be told apart with the tools available.
- Unchecked leads from these proposals, not findings: in neatlogs a Responses stream with status `failed` shows the run OK with no error recorded (v1 and v2), and an Anthropic 529 on a stream exports no span (v1). Neither has been through `trueup check`.
- The earlier v1 planner runs (prompt before its corrections) accepted 1 of 6 proposals on the first try.

### Evidence bundle, verify and report

- `trueup fix <id> --reprove` (no model call) applies the committed `patch.diff` to the clean clone, sweeps all 57 scenarios again and writes `fixes/<id>/proof.json` with every lead before and after. It reproduced all three recorded results: OpenLLMetry 32 (22 high) → 27 (17 high), OpenInference 19 (7) → 14 (2), neatlogs 35 (11) → 31 (9), 0 new mismatches.
- `trueup bundle` writes `evidence/` (179 files, 454 KB). Each of the 32 findings has finding.json (rules, dedupe log, upstream link), scenario.json, truth.json, spans.json and repro.py; fixed findings also have proof.json, patch.diff and graph.json. Spans keep only attributes the comparer reads, and the trimmed spans are kept only if the comparer gives the same leads on them. Also in the bundle: runs.json (run id, kind, versions, neatlogs session), withdrawn.json (4 by `latest_and_main`, 27 of Trueup's own finish false alarms; 10 disputed groups), v1v2.json, Neatlogs read evidence and manifest.json.
- `trueup verify` needs only `evidence/`: it checks every sha256 (and that no file is missing or extra), re-runs the comparer on every finding's truth and spans and on the after-patch spans, recomputes every headline number and the v1/v2 table, and compares them with headline.json. Tests change one byte, add or remove a file, edit a number and fix up the manifest to match, or edit spans so the bug is gone; each one fails.
- `trueup report` writes `docs/index.html` only if the bundle verifies: plain HTML and CSS, no scripts, light and dark, phone width, the same bytes for the same bundle. Order: headline tables, the OpenInference crashed-run-shown-OK finding from start to finish, all findings, withdrawn leads, upstream drafts (not yet posted).
- `action.yml`: a composite GitHub Action that runs `trueup audit <script> --library <lib>` and uploads `.trueup/runs/`. `entire-trueup` console script: `entire trueup verify` worked through Entire CLI 0.11.4.

### Judge path, timed

From a fresh clone of the working tree (copied into a temp git repo inside `.trueup/`, since nothing here is committed), with no keys set and an empty uv cache:

| step | exit | time |
|---|---|---|
| `uv sync` | 0 | 2 s (246 MB downloaded) |
| `uv run pytest -q` | 0 | 28 s |
| `uv run trueup verify` | 0 | under 1 s |
| `uv run trueup sweep openllmetry --case ag-run` | 1 (a lead) | 16 s, venv build included |

The sweep shows the double count: 2 provider calls, 4 LLM spans. Exit 1 means a lead was found. The download time depends on the network.

Spend for this session: key at $5.9869 before, $7.2802 after ($1.29). The $15 guard stayed on; only `claude-sonnet-4.6` was called.

## 2026-10-11: the "missing" neatlogs traces were late, not lost

- A test trace sent at 17:22 UTC showed up in neatlogs search within 20 seconds; the SDK's delivery report showed no dropped spans and no export failures (OBSERVED).
- Searching again for every planner and fixer run: all 19 sessions are now in neatlogs, including the four planner sessions that searched as empty last night (OBSERVED).
- Many of those traces carry a neatlogs time of 06:51–06:56 UTC, for runs made between 00:00 and 01:45 UTC. So neatlogs took them in about five hours late; Trueup sent them on time (OBSERVED from the timestamps; why neatlogs was late is not known).
- So the earlier line "the per-worker flush did not help" was measuring neatlogs' delay, not Trueup's sending. Nothing in Trueup's tracing code was changed for this.

## 2026-10-11: neatlogs detections on Trueup's own traces

- Each worker trace showed an empty output in neatlogs. Two causes (OBSERVED): `neatlogs.trace()` keeps its own context, so `opentelemetry.trace.get_current_span()` was another span and our attributes went nowhere; and neatlogs shows only its own keys, so `trueup.verdict` never appeared. Trueup now uses the span `trace()` yields and also writes the verdict as the span output (`neatlogs.agent.output` and `output.value`). After the change a checker trace shows "12 findings from 31 leads, 0 withdrawn" as its output. Test: `test_verdict_and_labels_go_where_neatlogs_reads_them`.
- The checker verdict now says how many leads it withdrew.
- Four detections, created through the neatlogs MCP server in a "Trueup" group: checker withdrew a lead; fix attempt failed (did not apply, or failed the verifier); model reply was not JSON (prose at the start of the reply); command could not run.
- First backfill over 14 days (OBSERVED): "model reply was not JSON" flagged 21 of 34 model calls. This matches the v1 waste: replies that open with prose. In v2 most of these still parse, because v2 takes the first JSON object in the reply, so the name overstates it: it flags prose before the JSON, not a failed parse. The other three detections had nothing to match yet, because older traces carry no output; they apply to runs from 18:00 UTC on.
- A fresh OpenLLMetry sweep + check (`20261011T180637Z-openllmetry`) withdrew 2 leads by the latest_and_main rule; its checker trace should fire "checker withdrew a lead" once neatlogs has taken it in.
- Not yet explained: the neatlogs release sweep now shows 31 leads where earlier runs showed 35.
- Correction (OBSERVED, 18:40 UTC): detections cannot match the output text of an agent span, though the trace view shows it. A rule on the checker's output ("2 withdrawn") matched nothing, while a rule on the span name matched every checker run. So events a detection must see are now their own named child steps (`tracing.mark`): "lead withdrawn" (one per withdrawn lead, with its scenario and the rule that failed), "fix attempt failed" (apply or verify) and "command could not run". New detections match those names. "Trueup: lead withdrawn (own false alarm)" fired twice on the next OpenLLMetry check (`20261011T180637Z-openllmetry`, both by latest_and_main). The three output-text detections are retired.

## 2026-10-11 hand-back for SPEC-FINISH sections 1b and 3–8

### Changed

- **OBSERVED:** Planner and fixer resume checkpoints are implemented. A paid draft is saved before verification;
  a resumed run reuses it. The final unit suite passed 352 tests, with 19 e2e tests excluded from that command.
- **OBSERVED:** Neatlogs SDK Doctor passed locally and through authenticated read-back. Probe trace
  `1103d1741d0642eb9f5fb5349414e2f0` was visible and finalized with four spans, valid hierarchy and attributes,
  and no duplicate or dropped span. Trueup now calls SDK `flush()` and `shutdown()` on normal and crash exits.
- **OBSERVED:** `trueup evidence pull` captured 10 detections and trends, six analytics views, and every fix-board
  state through read-only MCP. Neatlogs returned no fix suggestions. The bundle includes those JSON files.
- **OBSERVED:** `trueup audit --neatlogs` enables SDK PII redaction and emits one named `Trueup mismatch` child
  span per mismatch, with scenario/check/field/severity but no prompt or output value.
- **OBSERVED:** Four managed prompts (`trueup-planner-v1/v2`, `trueup-fixer-v1/v2`) exist with label
  `production` and read back exactly. `prompts/` contains exact offline copies and SHA-256 hashes.
- **OBSERVED:** The two unchecked Neatlogs scenarios are checked. The Anthropic 529 stream exports no span and
  matches existing issue #174. A failed OpenAI Responses stream produced three confirmed mismatch records: root
  OK, no error record, and no finish reason. Together they add three finding groups; the verified total is now
  32 findings (15 high, 17 medium), 5 already known, and 3 of 3 patches proven.
- **OBSERVED:** Evidence now includes Neatlogs failure-run IDs, per-comparison-run trace links, and six Entire
  checkpoint explanations. The report and README use the recomputed 32-finding headline. The graph ranked a
  patched function first in 0 of 3 fixes.
- **OBSERVED:** CI now separates unit/verify from a three-library e2e matrix. Foreground e2e results were 9 passed
  for Neatlogs, 9 for OpenInference, and 9 for OpenLLMetry.
- **OBSERVED:** A fresh copy with no local run state completed `uv sync` in 1.20 s, 352 tests in 36.72 s,
  `trueup verify` in 0.17 s, and `trueup demo` in 0.14 s.
- **OBSERVED:** `docs/video-script.md` is timed to 2:55 and has three terminal takes. `docs/posts.md` contains M7,
  M8, submission, and final quote-post drafts. Nothing was posted.
- **OBSERVED:** The duplicate business plan was removed. `docs/business-plan.md` is the one plan, links the cfo.ai
  share, and separates measured model costs from proposed pricing.

### Owner actions / not done

- **REPORTED:** Dashboard screenshots are still needed for workflows/attributes, v1/v2 filters, detections,
  prompt history, and failed-then-passed replay. Exact shots and trace IDs are in `docs/neatlogs.md`.
- **OBSERVED:** The ingest credential cannot create AI evaluations, alerts, comments, or human evaluations, and
  no service-account Public API credential was supplied. `docs/neatlogs.md` gives the exact rubric, alert, and
  comments. MCP is used for reads. No fix investigation was spent because the board returned no fix card and
  exposed no investigation-creation tool.
- **OBSERVED:** GitHub Pages was not enabled because publication needs owner approval. The report remains
  `docs/index.html` and no public report URL is claimed.
- **OBSERVED:** No upstream issue or PR was posted. The required latest-release rerun is scheduled for the morning
  of 12 Oct, then each of the three drafts needs owner approval. Check whether the OpenLLMetry draft duplicates
  PR #4377 before posting.
- **OBSERVED:** No video was rendered and no X post was sent. The owner chooses the voice, records dashboard
  shots, publishes the video, fills the post URL placeholders, and posts the final quote between 13:30 and
  18:25 UTC on 12 Oct 2026.
- **OBSERVED:** No real OpenAI or Anthropic provider key was supplied for the final recording-proxy cross-check.
  The proxy itself has subprocess tests proving forwarded credentials are absent from its JSONL record.
- **OBSERVED:** Crustdata was not used: Trueup checks tracing code and needs no company or people data.

Everything above is left uncommitted for owner review. No public action was taken.

### Checked by the owner's session after the hand-back (2026-10-11)

- The "neatlogs 35 → 31 leads" question is answered, and nothing changed in neatlogs (OBSERVED): 35 was counted over 57 scenarios (51 built-in + 6 planner proposals, the `fix --reprove` set); today's plain sweep runs the 51 built-in ones and shows 31. The 51-scenario sweep from 10 Oct showed 58 before the adapter fix removed 27 false leads: 58 − 27 = 31.
- Not done from the finish list: a real fixer run that fails a try, to show the "fix attempt failed (retried)" detection firing.
- X post, 11 Oct: https://x.com/jennyoliver57/status/2109360422029594753
- X post 3, 12 Oct: https://x.com/jennyoliver57/status/2109546774025113763
- X thread (Arize review, light out, neatlogs PR, email), 12 Oct: https://x.com/jennyoliver57/status/2109652614459633672

## 2026-10-12: more Neatlogs fixes, checked against every open wrapper PR

- **OBSERVED:** Every confirmed Neatlogs finding repro was run on the head of every open PR that touches its
  wrapper file. The machine-readable matrix covers 11 PRs. PR #180 fixes all four Anthropic stream data findings;
  PR #186 fixes the non-streamed Responses tool-call finding but not the other five findings tested against it.
  Those findings were not duplicated.
- **OBSERVED:** The first refusal-output fixer run failed three times because Entire returned valid but unrelated
  graph hits, and Trueup then skipped its exact seed-symbol lookup. The locator now always merges seed definitions
  after graph results. Its regression test proves an off-target graph result cannot hide the named wrapper.
- **OBSERVED:** The corrected run fixed non-streamed OpenAI refusal output on its first try. The new test fails on
  the clean library and passes with the patch. The package suite has the same one pre-existing collection failure;
  the 57-scenario sweep changed 35 leads to 34 with no new mismatch. The standalone repro prints `None` before
  and the refusal text after. A maintainer-ready issue and PR draft are in `upstream/`.
- **OBSERVED:** The Responses stream error-event fix passed on try 2. Try 1 passed its unit test but the real
  scenario rejected it. The accepted patch changes the stream span from OK with no exception event to ERROR with
  one exception event. The full sweep changed 35 leads to 33 (one high and one medium removed), with no new
  mismatch. A maintainer-ready issue and PR draft are in `upstream/`.
- **OBSERVED:** The OpenAI Agents root-status candidate was dropped after three tries. Every draft passed its
  generated unit tests, but all five real failure scenarios still exported an OK root. No patch or PR is offered.
- **OBSERVED:** Model-key spend for this milestone went from $7.6712 to $8.9404: $1.2692 total, below the $2.50
  limit. Only `claude-sonnet-4.6` was called. Nothing was posted.

## 2026-10-11: first fixes sent upstream

Before posting, each repro was re-run on the latest release, on `main`, and with every open PR that touches the patched files installed (OBSERVED):

- OpenInference 2.5.3, `main` c364180 and open PRs #3493, #3856, #3901: still OK on a failed run. Posted issue [#4023](https://github.com/Arize-ai/openinference/issues/4023) and PR [#4024](https://github.com/Arize-ai/openinference/pull/4024).
- OpenLLMetry 0.62.4, `main` 17d0c5a and 12 open PRs: still 2 LLM spans and 14 tokens for 1 call and 7 tokens. Posted issue [#4609](https://github.com/traceloop/openllmetry/issues/4609) and PR [#4610](https://github.com/traceloop/openllmetry/pull/4610).
- neatlogs: the bug was already reported by the neatlogs team on 5 Oct (#179, fix PR #180). Not filed again. PR #180's head (95440a5) turns our repro from OK / 0 exception events into ERROR / 1; [posted that as a comment](https://github.com/neatlogs/neatlogs/pull/180#issuecomment-6113318503).

Three mistakes caught on the way, each one now a lesson for Trueup:

1. **The deduper missed a duplicate.** It searched two narrow phrases ("anthropic span status error stream", "span status error stream") and found nothing, but #179's title says "loses output and reports OK on mid-stream errors". A wider search found it. Next change: search the wrapper's function and file names and the symptom in several wordings, and list every open issue on the touched file.
2. **A false "regression".** Old OpenLLMetry code looked correct (1 span) only because the newest `traceloop-sdk` passed a keyword (`use_attributes`) that the old instrumentation rejects, so it never started. With matching versions the old code double-counts too. The issue does not call it a regression.
3. **Two of the fixer's unit tests passed without the fix.** They used `MagicMock` responses, which the Responses wrapper never turns into a span, fix or no fix. They also lived in a package whose test environment does not install the OpenAI instrumentation. The posted PR moves them to the OpenAI package and uses a real client with `httpx.MockTransport` and a new response id per call (the wrapper keeps responses by id, so a repeated id also hid the span). They now fail without the fix (2 of 3) and pass with it. Next change: the verifier must require that every new test fails before the patch, not just one.

A failed fixer run, kept as evidence (`fixes/openinference-.../runs/20261011T194424Z-fix-openinference.json`, $0.39): all 3 tries failed (two tests failed with the patch; the third broke `ag-tool-raises`), and Trueup reported "NOT fixed". It also overwrote the earlier proven fix's files in `fixes/`; they were restored from git. Next change: a failed run must never replace a proven fix.

## 2026-10-12: JSON response mode and another failed-fix proof

- **OBSERVED:** v3 asks the model proxy for JSON response mode and uses shorter, committed planner and fixer
  prompts. Two planner runs accepted 6 proposals using 4 model calls and no JSON retry. One fixer run used 3
  calls and no JSON retry. This proves the proxy accepts JSON response mode for `claude-sonnet-4.6`; it does not
  prove that v3 plans or fixes better than v2.
- **OBSERVED:** The v3 fixer run `20261012T021600Z-fix-openinference` did not fix the OpenInference root-status
  finding. Try 1 used a disallowed test filename, try 2 created a new mismatch in `ag-tool-raises`, and try 3's
  new test still failed after the patch. Trueup kept the three failed tries and reported `fixed: false`; no proven
  fix was replaced. The run cost recorded by the proxy was $0.253265.
- **OBSERVED:** The read-only Neatlogs detection pull at 10:03 UTC reports 13 occurrences for `Trueup: fix
  attempt failed (retried)`: 6 on 11 Oct and 7 on 12 Oct. This closes the required proof that a real failed fixer
  try reaches the detection; the raw trend is in `evidence/neatlogs/detections.json`.

## Hand-back, 12 Oct (witness)

- Earlier work: `8e50fe6`, complete; 364 tests passed before the commit.
- W1 Witness: `c9cf1fe`, complete. Sync and async provider traffic, stream completion, cuts, error events, refusal, tools and usage are observed without changing application return values.
- W2 live demo: `81ec337`, complete. Real LiteLLM traffic reproduced an Agents workflow shown OK and an Anthropic cable cut shown OK. Twenty normal calls produced zero disagreements.
- W3 rerate: `1f5008a`, complete with a negative result. All three proven neatlogs patches applied together; targeted marks stayed 2 → 2. The one allowed new fixer attempt cost $0.30826290, but overlapping resume processes left its patch artifact empty, so it was rejected.
- W4 words: this commit. README, page, video, posts and cfo.ai inputs lead with Witness and retain the failed after result.
- Model-key spend: $9.53811870 before the gate; $9.85278360 after the live work and fixer; increase $0.31466490. The gate itself cost $0.00626780; the later fixer and probes account for the rest.
- Not done: no alert destination was connected because MCP exposes detection creation but no alert-rule write tool. No patch was called fixed. Nothing was pushed or posted.

## 2026-10-12 12:15 UTC: the light goes out (2 → 0)

- OBSERVED: with real Claude Haiku and OpenAI Agents traffic, both targeted breaks put a `TRACE DISAGREE` step in
  neatlogs before the patches (`5322259c…`, `a4074bff…`) and none after (`7304699b…`, `83f710d1…`). `trueup verify`
  recomputes 2 → 0 from `evidence/witness/`.
- OBSERVED: 40 normal real calls (20 before, 20 after), 0 disagreements. Spend $0.0123794 for all of it.
- OBSERVED: why the morning attempt stayed 2 → 2. The relay's partial stream had no `content_block_start`, so the
  Anthropic SDK failed on bad data rather than on a cut. Witness treated "ERROR without an exception event" as OK.
  And the Agents path was never patched: `neatlogs.init(instrumentations=["openai_agents"])` runs OpenInference's
  processor (neatlogs `instrumentation/registry.py`), so the fix is Arize-ai/openinference#4024, here at `4352755`
  after the maintainer's suggestions. Witness also counted its own mark step, turning one lie into two marks.
  All four are fixed, with tests in `tests/test_witness.py`.
- OBSERVED: `examples/shop_agent.py` used to print "neatlogs record: OK" and "DISAGREE light: ON" whenever the app
  crashed, without asking Witness. It now prints only Witness's own verdict.
- DOCUMENTED: neatlogs' own `openai_agents_processor()` has the same Agents bug. A fix with 6 tests (2 fail before,
  6 pass after; unit suite 534 passed, the same 5 missing-dependency failures before and after) is drafted in
  `upstream/neatlogs-openai-agents-processor-run-status/`. Not posted.
- Still not perfect (OBSERVED): the agent's model step is ERROR with no exception event, reported as a note; an
  inner step also named "Agent workflow" still ends SUCCESS.
- OBSERVED 12:40 UTC: posted the neatlogs Agents recorder fix as issue neatlogs/neatlogs#206 and pull request
  #207 (owner approved). On neatlogs main, the full unit suite passes as their CI installs it (536 passed, 4 skipped;
  the new tests skip without `openai-agents`). With openai-agents 0.23.1, the 6 new tests fail 2 without the fix
  and all pass with it. black and isort are clean.

## What Entire recorded, and what it did not (12 Oct, OBSERVED)

Entire recorded the build of Trueup's core: 10 commits from `dadba2f` (skeleton, 10 Oct) to `88fcc91` (evidence
bundle and report, 11 Oct), each with an `Entire-Checkpoint` trailer. That covers the test lab, comparer, checker,
planner, the fixer that wrote and proved the first patches, and the Entire graph step that located them.

The 20 commits from `56d705d` (11 Oct 18:50) to `6ea4eee` (12 Oct) have **no Entire record**. That work (neatlogs
detections, the upstream PRs, Witness, the light going out, the live app) was done in sessions started outside
this folder, so Entire's hooks never ran. We noticed on 12 Oct and did not
create records afterwards: a record made later would not show how the work was really done. From 12 Oct ~14:35 UTC
all work runs again in sessions started in this folder, so Entire records it.
