# Locate re-run: neatlogs-run_status-anthropic-messages-stream-top-level-span-status-ok

Method: entire graph (entire graph search, neighbors and impact). Clone commit 202f8776ea.
Query: anthropic messages stream tracing: top-level span status is OK in the span but really ERROR (app raised RemoteProtocolError) (neatlogs, anthropic messages stream: top-level span status is OK)

| patched function | file | graph rank | ripgrep + ast rank | among graph callers |
|---|---|---|---|---|
| _SyncStreamManagerWrapper.__exit__ | neatlogs/anthropic.py | not found | only its class, at 3 | no |
| _SyncStreamManagerWrapper._finalize | neatlogs/anthropic.py | not found | only its class, at 3 | no |
| _AsyncStreamManagerWrapper.__aexit__ | neatlogs/anthropic.py | not found | only its class, at 5 | no |
| _AsyncStreamManagerWrapper._finalize | neatlogs/anthropic.py | not found | only its class, at 5 | no |

Graph found 0 of 4 patched functions, 0 in its top 3 (the ones followed up with neighbors and impact). Ranked first: no.

Graph top hits:

1. SyncStreamWrapper._finalize_error (neatlogs/_wrap_utils.py, score 62.2699)
2. AsyncStreamWrapper._finalize_error (neatlogs/_wrap_utils.py, score 62.2324)
3. NeatlogsConfigurationError (neatlogs/errors.py, score 61.7159)
4. _reject_http_span_kind (neatlogs/core/context.py, score 56.9505)
5. _trace_sampler (neatlogs/init.py, score 56.9505)
6. AsyncStreamWrapper.__anext__ (neatlogs/_wrap_utils.py, score 0)
