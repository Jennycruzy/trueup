# neatHack post drafts — owner approval required

Posted so far:

- 2026-10-11, Day 2: Trueup watching itself in neatlogs (the "model reply was not JSON" and "lead withdrawn" detections): https://x.com/jennyoliver57/status/2109360422029594753

The drafts below are not posted yet. Replace every bracketed placeholder only after the linked item is public.
Numbers below come from `trueup verify`.

## M7 — v1 versus v2

We used Trueup's own Neatlogs traces to revise the fixer, then ran v1 and v2 on the same OpenInference bug.

v1: 4 model calls, 2 JSON retries, $0.53.
v2: 2 model calls, 0 JSON retries, $0.22.

Both fixes passed; v2 removed the avoidable retries. Evidence: [PUBLIC_REPORT_URL]

#neatHack @neatlogs @EntireHQ

## M8 — first upstream issue

Trueup found [ONE-SENTENCE_BUG], reproduced it twice, checked the latest release and main, and proved a patch
against the package suite and all 57 scenarios.

Issue: [ISSUE_URL]
Verified evidence: [PUBLIC_REPORT_URL]

The issue is public only after maintainer-facing review. #neatHack @neatlogs

## Submission post

Trueup finds where AI-agent traces disagree with what really happened, fixes the tracing code, and proves the fix.

32 confirmed findings across neatlogs, OpenInference, and OpenLLMetry: 15 high, 17 medium. Three of three drafted
patches passed their target cases, package suites, and the full 57-scenario library with no new mismatch.

Demo: [VIDEO_URL]
Evidence: [PUBLIC_REPORT_URL]
Repo: https://github.com/Jennycruzy/trueup

#neatHack @neatlogs @EntireHQ

## Final quote-post of the official Neatlogs post

Team: Jenny builds
Builder: Jenny Oliver
Project: Trueup

Trueup checks whether AI-agent traces tell the truth, repairs instrumentation bugs, and proves each repair. Our
verified evidence contains 32 findings and 3 proven patches.

Repo: https://github.com/Jennycruzy/trueup
Demo: [VIDEO_URL]
Evidence: [PUBLIC_REPORT_URL]

#neatHack @neatlogs @EntireHQ

Post this only as a quote-post of the official Neatlogs post on 12 Oct 2026 between 13:30 and 18:25 UTC. Send the
published URL back so it can be added to README and evidence.
