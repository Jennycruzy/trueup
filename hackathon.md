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
