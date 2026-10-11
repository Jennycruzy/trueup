# openinference-run_status-openai-agents-top-level-span-status-ok

openinference, openai-agents: top-level span status is OK

Library commit: c364180e5be52f0cdc00fbc88f9462603569f4e2. Located with ripgrep + ast (fallback).
Model: claude-sonnet-4.6; cost $0.633006 (key spend delta); run 20261011T004013Z-fix-openinference.

Result: fixed: the new test fails before and passes after, the suites show no new failure, the finding's scenarios match truth and the full scenario library has no new mismatch.

## Tries

1. FAIL at verify: the new test fails with the patch (exit 1): instance has not been set on this response.
------------------------------ Captured log call -------------------------------
ERROR    openai.agents:run_loop.py:1660 Error getting response; filtered.input=[{'content': 'hi', 'role': 'user'}]
_______________ test_root_span_is_error_when_max_turns_exceeded ________________
tests/test_trueup_root_span_status.py:133: in test_root_span_is_error_when_max_turns_exceeded
    assert root.status.status_code == StatusCode.ERROR, (
E   AssertionError: root span status should be ERROR, got StatusCode.OK
E   assert <StatusCode.OK: 1> == <StatusCode.ERROR: 2>
E    +  where <StatusCode.OK: 1> = <opentelemetry.tra...
   Model's explanation: In on_trace_end the root span is unconditionally given Status(StatusCode.OK), ignoring any errors that occurred during the run. The fix tracks whether a direct child of the root span ended with ERROR status and propagates that error to the root span in on_trace_end. We add a _root_span_errors dict to store the error status keyed by trace_id, populated in on_span_end when a span with ERROR status has no parent in _otel_spans (meaning its parent is the root span).
2. FAIL at verify: the new test fails with the patch (exit 1): /run.py:1054: in run
    turn_result = await model_task
                  ^^^^^^^^^^^^^^^^
../../../../../venvs/openinference-fixtest-openinference-instrumentation-openai-agents/lib/python3.12/site-packages/agents/run_internal/run_loop.py:1499: in run_single_turn
    new_response = await get_new_response(
../../../../../venvs/openinference-fixtest-openinference-instrumentation-openai-agents/lib/python3.12/site-packages/agents/run_internal/run_loop.py:1594: in get_new_response
    new_response = await model.get_response(
E   TypeError: _ToolRaisesModel.get_response() got an unexpected keyword argument 'conversation_id'
---------------------------...
   Model's explanation: The root span always gets StatusCode.OK because on_trace_end unconditionally sets it. The fix tracks ERROR status from non-FunctionSpanData spans per trace_id, then applies it to the root span in on_trace_end. FunctionSpanData errors are non-fatal (tool raises but run continues), so they are excluded. This covers all failing scenarios while keeping ag-tool-raises as OK.
3. PASS at verified: all 5 scenario(s) of the finding now match truth here
   Model's explanation: The root span always gets StatusCode.OK because on_trace_end unconditionally sets it. The fix tracks ERROR status from non-FunctionSpanData spans per trace_id, then applies it to the root span in on_trace_end. FunctionSpanData errors are non-fatal (tool raises but run continues), so they are excluded. The test models need to accept **kwargs to be forward-compatible with new SDK keyword arguments.

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

