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
