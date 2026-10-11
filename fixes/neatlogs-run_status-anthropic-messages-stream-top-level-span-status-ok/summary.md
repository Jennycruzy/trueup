# neatlogs-run_status-anthropic-messages-stream-top-level-span-status-ok

neatlogs, anthropic messages stream: top-level span status is OK

Library commit: 202f8776ea7d0902a6cb085495c6bcb00c226f8e. Located with ripgrep + ast (fallback).
Model: claude-sonnet-4.6; cost $0.400501 (key spend delta); run 20261011T005144Z-fix-neatlogs.

Result: fixed: the new test fails before and passes after, the suites show no new failure, the finding's scenarios match truth and the full scenario library has no new mismatch.

## Tries

1. PASS at verified: all 2 scenario(s) of the finding now match truth here
   Model's explanation: When messages.stream() raises during iteration (e.g. RemoteProtocolError or APIStatusError), the exception propagates through __exit__/__aexit__ which calls _finalize() unconditionally. _finalize() always calls _finalize_stream() which sets StatusCode.OK. The fix is to detect a live exception in __exit__/__aexit__ and record it as an error on the span instead of calling _finalize_stream with OK status.

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

