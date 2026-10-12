# Managed prompts

These are the reviewed offline copies of Trueup's managed system prompts. The runtime asks Neatlogs for the
matching prompt's `production` label only when tracing is configured. If that read fails, it uses the same text
embedded in the package. `manifest.json` records each copy's SHA-256 hash.

- `planner-v1.txt` and `planner-v2.txt`: scenario proposals; both versions use the same system instruction.
- `fixer-v1.txt`: patch and regression-test drafting.
- `fixer-v2.txt`: the v1 instruction plus the strict JSON-first instruction that reduced paid retries.
- `planner-v3.txt` and `fixer-v3.txt`: shorter JSON-only instructions used with the proxy's JSON response mode.
