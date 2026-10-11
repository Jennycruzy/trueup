| scenario | field | truth | before | after |
|---|---|---|---|---|
| p-an-stream-helper-cut | top-level span status | ERROR (app raised RemoteProtocolError) | OK | matches truth |
| p-an-stream-helper-error-event | top-level span status | ERROR (app raised APIStatusError) | OK | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 35 | 11 | 24 |
| after | 57 | 0 | 31 | 9 | 22 |
