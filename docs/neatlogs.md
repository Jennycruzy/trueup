# Neatlogs hand-back

Trueup uses Neatlogs for its own worker traces while keeping scenario traces local. Machine-readable detections,
trends, analytics, failure-run IDs, and fix-board reads are included under `evidence/neatlogs/`.

## Confirmed read-back

The official SDK Doctor probe passed visibility, finalization, hierarchy, attributes, input/output, metadata, and
typed-token checks. Its trace ID is `1103d1741d0642eb9f5fb5349414e2f0`; it persisted four spans with no duplicate
or dropped span. Trueup now calls both `flush()` and `shutdown()` on normal and exceptional exits.

Required story links:

- [Fixer try 1 failed verification](https://app.neatlogs.com/traces/c039eb266bd9aa8f3c0d856b32cbc33a),
  followed by [try 2 passing](https://app.neatlogs.com/traces/2268109cee7503a2a3b56b546ea7a47a).
- [Checker trace that withdrew two leads](https://app.neatlogs.com/traces/839ae73860ddabecafd0b45e3b0b3334).

## Owner dashboard actions

These cannot be created with the project ingest credential or the available read-only MCP calls.

1. AI evaluation: question “Is every confirmed finding backed by all seven passing checker rules and a runnable
   reproduction?” Score 1 only if both are present, otherwise 0. Run on `trueup-checker` traces, compare tags
   `variant:v1` and `variant:v2`, and keep the score advisory—it must never decide a finding.
2. Alert: detection `Trueup: lead withdrawn (own false alarm)`, threshold at least one match in 15 minutes.
3. Add a comment to the failed fixer verifier trace: “Try 1 reached the full scenario sweep and introduced a
   regression; code rejected it.” Add to the passing trace: “Try 2 passed the new test, package suite, target
   scenarios, and full sweep.”
4. Capture screenshots of workflow `trueup`, worker names, v1/v2 filters, the four prompt histories, detection
   hits, and the failed-then-passed trace replay.
5. In **Detections**, filter to group `Trace truth (by Trueup)` and capture the list showing all three active
   conditional rules.
6. Open detection `neatlogs: LLM output was not recorded`, select a 12 October occurrence, and capture the detection
   beside demo trace `6041090c2877aa7d78861796ee052fcb` (`anth-plain`, empty output). Also capture the zero-token
   rule's trend showing six occurrences on 12 October.

Neatlogs returned no fix suggestions in draft, open, in-progress, resolved, or archived states, so there was no
suggestion to accept or reject. No investigation was spent because no fix card or investigation-creation MCP tool
was available. Alert history and human evaluations likewise remain dashboard owner actions. The Public API read
correctly returned 401 for an ingest credential; MCP supplies the scoped reads instead.
