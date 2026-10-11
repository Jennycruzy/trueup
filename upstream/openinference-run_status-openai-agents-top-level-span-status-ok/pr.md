<!-- Drafted by Trueup from recorded runs. Not posted. -->

# fix(openai-agents): set the root span to ERROR when the agent run fails

## What

The root span always gets StatusCode.OK because on_trace_end unconditionally sets it. The fix tracks ERROR status from non-FunctionSpanData spans per trace_id, then applies it to the root span in on_trace_end. FunctionSpanData errors are non-fatal (tool raises but run continues), so they are excluded. The test models need to accept **kwargs to be forward-compatible with new SDK keyword arguments.

## Files

- `python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py`
- `python/instrumentation/openinference-instrumentation-openai-agents/tests/test_trueup_root_span_status.py`

## Test

new test: fails before (1 of 3 failing), passes after (3 passed); 2 of 3 new test functions also pass before the patch, so they do not show the bug: test_root_span_is_ok_when_run_succeeds, test_root_span_is_ok_when_tool_raises_but_run_succeeds.

Limit: any ERROR on a non-function span marks the run ERROR, so a span error the SDK later recovers from would also mark the root ERROR. No such case is in Trueup's scenarios.

## Suites

- `python/instrumentation/openinference-instrumentation-openai-agents` before the patch: 295 passed, 0 failing
- `python/instrumentation/openinference-instrumentation-openai-agents`: suite passes

## Before and after

| scenario | field | truth | before | after |
|---|---|---|---|---|
| ag-bad-tool | top-level span status | ERROR (app raised ModelBehaviorError) | OK | matches truth |
| ag-llm-fails | top-level span status | ERROR (app raised InternalServerError) | OK | matches truth |
| ag-max-turns | top-level span status | ERROR (app raised MaxTurnsExceeded) | OK | matches truth |
| ag-streamed-cut | top-level span status | ERROR (app raised APIConnectionError) | OK | matches truth |
| ag-streamed-error | top-level span status | ERROR (app raised ModelBehaviorError) | OK | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 19 | 7 | 12 |
| after | 57 | 0 | 14 | 2 | 12 |

The standalone repro from the issue, with this patch:

```
the run raised InternalServerError
top-level span 'Agent workflow': ERROR
```

Patch drafted by claude-sonnet-4.6 and verified by Trueup (3 tries in the last run; every try is in tries.json).
