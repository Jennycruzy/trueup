# How this fix was made: neatlogs-run_status-openai-responses-stream-top-level-span-status-unset

## Commit

First added in `2555765` on 2026-10-12: Prepare more neatlogs fixes

No Entire record for this commit.

## Fixer tries

2 tries; 1 failed.
- Try 1 failed: still wrong after the patch: oa-resp-stream-error-event. With the patch installed and the real scenario run, top-level span status: oa-resp-stream-error-event: truth ERROR (app raised RuntimeError), …
- Model: claude-sonnet-4.6
- Cost: $0.36

## Verifier

Leads across all scenarios: 35 before, 33 after. New mismatches: 0.

## Upstream

Draft, not posted: [upstream/neatlogs-run_status-openai-responses-stream-top-level-span-status-unset/](../../upstream/neatlogs-run_status-openai-responses-stream-top-level-span-status-unset/)
