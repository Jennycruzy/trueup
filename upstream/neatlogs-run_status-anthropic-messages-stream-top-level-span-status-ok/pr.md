<!-- Drafted by Trueup from recorded runs. Not posted. -->

# fix(anthropic): record an error on messages.stream() spans when the stream fails

## What

When messages.stream() raises during iteration (e.g. RemoteProtocolError or APIStatusError), the exception propagates through __exit__/__aexit__ which calls _finalize() unconditionally. _finalize() always calls _finalize_stream() which sets StatusCode.OK. The fix is to detect a live exception in __exit__/__aexit__ and record it as an error on the span instead of calling _finalize_stream with OK status.

## Files

- `neatlogs/anthropic.py`
- `tests/unit/test_trueup_anthropic_stream_error_status.py`

## Test

new test: fails before (2 of 3 failing), passes after (3 passed); 1 of 3 new test functions also pass before the patch, so they do not show the bug: test_successful_stream_produces_ok_span.

On failure the span gets the error and ends; partial text and tokens are not recorded.

## Suites

- `.` before the patch: 527 passed, 1 failing (tests.unit.test_google_finish_reason_value)
- `.`: same 1 failure(s) as before the patch

## Before and after

| scenario | field | truth | before | after |
|---|---|---|---|---|
| p-an-stream-helper-cut | top-level span status | ERROR (app raised RemoteProtocolError) | OK | matches truth |
| p-an-stream-helper-error-event | top-level span status | ERROR (app raised APIStatusError) | OK | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 35 | 11 | 24 |
| after | 57 | 0 | 31 | 9 | 22 |

The standalone repro from the issue, with this patch:

```
the app saw APIStatusError
span 'anthropic.messages.create': ERROR, exception events: 1
2026-10-11 01:14:47 - neatlogs - INFO - Neatlogs SDK shutdown complete
```

Patch drafted by claude-sonnet-4.6 and verified by Trueup (1 tries in the last run; every try is in tries.json).
