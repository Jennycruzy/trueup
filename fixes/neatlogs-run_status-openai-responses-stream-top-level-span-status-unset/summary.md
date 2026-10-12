# neatlogs-run_status-openai-responses-stream-top-level-span-status-unset

neatlogs, openai responses stream: top-level span status is UNSET

Library commit: 202f8776ea7d0902a6cb085495c6bcb00c226f8e. Located with entire graph + seed symbols.
Model: claude-sonnet-4.6; cost $0.35972 (key spend delta); run 20261012T010933Z-fix-neatlogs.

Result: fixed: the new test fails before and passes after, the suites show no new failure, the finding's scenarios match truth and the full scenario library has no new mismatch.

## Tries

1. FAIL at verify: still wrong after the patch: oa-resp-stream-error-event. With the patch installed and the real scenario run, top-level span status: oa-resp-stream-error-event: truth ERROR (app raised RuntimeError), trace UNSET. Spans exported with the patch ([name, status, description, parent]): oa-resp-stream-error-event: [['openai.responses.create', 'UNSET', '', None]]
   Model's explanation: When an OpenAI Responses stream delivers a `response.error` event, the SDK does not raise — the stream exhausts normally and `_finalize_responses_stream` is called with `interrupted=False`. That function never inspects events for error types, so it always sets `StatusCode.OK`, leaving the span with UNSET (since OK is only set when not interrupted, but the span status was UNSET before). The fix is to scan the collected chunks for any event whose `type` is `'response.error'` and, when found, se...
2. PASS at verified: all 1 scenario(s) of the finding now match truth here
   Model's explanation: The scenario says 'app raised RuntimeError' — meaning the app itself raises after consuming the stream, not that the SDK raises. The stream exhausts normally (StopIteration), so `_finalize_responses_stream` is called via `_finalize(interrupted=False)`. But the `response.error` event causes the app to raise RuntimeError *after* iterating. Looking more carefully: the stream wrapper's `__next__` catches `BaseException` and calls `_finalize_error`, but if the error event doesn't raise during iter...

## Before and after

| scenario | field | truth | before | after |
|---|---|---|---|---|
| oa-resp-stream-error-event | top-level span status | ERROR (app raised RuntimeError) | UNSET | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 35 | 11 | 24 |
| after | 57 | 0 | 33 | 10 | 23 |

