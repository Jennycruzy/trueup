# How this fix was made: openllmetry-call_count-openai-agents-llm-spans-wrong

## Commit

First added in `79210a4` on 2026-10-11: Add fixer, verifier and upstream drafts

Entire record: checkpoint `01M4M8M1GSQ2BM1RX2JKDJHPD6`, [https://entire.io/gh/Jennycruzy/trueup/commit/79210a45418246ceb95e2990d1c003b5fbc7b3d9](https://entire.io/gh/Jennycruzy/trueup/commit/79210a45418246ceb95e2990d1c003b5fbc7b3d9)

## What the session did

```
● Checkpoint 01M4M8M1GSQ2BM1RX2JKDJHPD6
  session  46884b07-6b3f-4c42-8278-37fcc40e87a6
  created  2026-10-11 01:18:18
  author   Jennycruzy <jennycruzy@users.noreply.github.com>
  tokens   13674k
  commits  79210a4 Add fixer, verifier and upstream drafts
────────────────────────────────────────────────────────────
## Intent

Continue building Trueup in this repository. Read README.md, hackathon.md, CH...
```

## Fixer tries

3 tries; 2 failed.
- Try 1 failed: still wrong after the patch: ag-bad-tool, ag-llm-fails, ag-max-turns, ag-run, ag-tool-raises. With the patch installed and the real scenario run, LLM spans: ag-bad-tool: truth 1 (provider requests), …
- Try 2 failed: packages/opentelemetry-instrumentation-openai-agents: 1 test(s) fail in the full suite after the patch and did not fail before: .trueup.clones.openllmetry.packages.opentelemetry-instrumentation-opena…
- Model: claude-sonnet-4.6
- Cost: $0.65

## Verifier

Leads across all scenarios: 32 before, 27 after. New mismatches: 0.

## Upstream

Posted: https://github.com/traceloop/openllmetry/pull/4610
