| scenario | field | truth | before | after |
|---|---|---|---|---|
| oa-resp-stream-error-event | top-level span status | ERROR (app raised RuntimeError) | UNSET | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 35 | 11 | 24 |
| after | 57 | 0 | 33 | 10 | 23 |
