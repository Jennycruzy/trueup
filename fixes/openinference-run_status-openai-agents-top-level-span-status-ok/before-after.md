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
