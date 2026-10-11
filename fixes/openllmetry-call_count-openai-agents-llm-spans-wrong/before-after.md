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
