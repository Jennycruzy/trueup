<!-- Drafted by Trueup from recorded runs. Not posted. -->

# fix(openai-agents): record one LLM span per model call

## What

The responses_get_or_create_wrapper (and async counterpart) only checks _SUPPRESS_INSTRUMENTATION_KEY but not SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY. When the openai-agents processor sets that key for a generation span, the openai instrumentation ignores it and creates a duplicate span. Fix: check SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY in both wrappers, and set it in the agents processor when starting generation spans. The async test also needs to use pytest-asyncio or a fresh event loop instead of get_event_loop().

## Files

- `packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_hooks.py`
- `packages/opentelemetry-instrumentation-openai-agents/tests/test_trueup_llm_span_count.py`
- `packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/v1/responses_wrappers.py`

## Test

new test: fails before (1 of 4 failing), passes after (4 passed); 3 of 4 new test functions also pass before the patch, so they do not show the bug: test_sync_wrapper_suppressed_when_key_set, test_async_wrapper_suppressed_when_key_set, test_non_generation_spans_do_not_suppress.

The new test functions that also pass without the patch guard the change but do not show the bug; the scenario table and the repro are the end-to-end proof.

## Suites

- `packages/opentelemetry-instrumentation-openai-agents` before the patch: 405 passed, 1 failing (test_none_finish_reason_omits_attribute)
- `packages/opentelemetry-instrumentation-openai` before the patch: 291 passed, 0 failing
- `packages/opentelemetry-instrumentation-openai-agents`: same 1 failure(s) as before the patch
- `packages/opentelemetry-instrumentation-openai`: suite passes

## Before and after

| scenario | field | truth | before | after |
|---|---|---|---|---|
| ag-bad-tool | LLM spans | 1 (provider requests) | 2 | matches truth |
| ag-llm-fails | LLM spans | 2 (provider requests) | 4 | matches truth |
| ag-max-turns | LLM spans | 3 (provider requests) | 6 | matches truth |
| ag-run | LLM spans | 2 (provider requests) | 4 | matches truth |
| ag-tool-raises | LLM spans | 2 (provider requests) | 4 | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 32 | 22 | 10 |
| after | 57 | 0 | 27 | 17 | 10 |

The standalone repro from the issue, with this patch:

```
Traceloop exporting traces to a custom exporter

Metrics are disabled
provider requests: 1; LLM spans: 1; output tokens on LLM spans: 7 (provider sent 7)
```

- [x] I have added tests that cover my changes.
- [ ] If adding a new instrumentation or changing an existing one, I've added screenshots from some observability platform showing the change. (Not done: the change was checked with in-memory spans, see the table.)
- [x] PR name follows conventional commits format: `feat(instrumentation): ...` or `fix(instrumentation): ...`.
- [ ] (If applicable) I have updated the documentation accordingly. (Not applicable.)

Patch drafted by claude-sonnet-4.6 and verified by Trueup (3 tries in the last run; every try is in tries.json).
