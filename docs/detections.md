# Trace-truth detection map

Trueup grouped the confirmed findings by the signature visible in Neatlogs. A conditional detection can inspect one
span; relationships between spans require the code engine.

| Finding group | Trace signature | Engine | Shipped as |
|---|---|---|---|
| Missing streamed output | LLM span has empty output although the fake returned text | conditional | `LLM output was not recorded` |
| Missing streamed usage | LLM span has `total_tokens = 0` although the fake returned usage | conditional | `LLM token count was not recorded` |
| Success hides missing output | LLM span is OK and its output is empty | conditional | `LLM succeeded without output` |
| Responses stream error | app raises while the provider LLM span remains OK/UNSET | trace-level | `crashed_run_ok.py` (the single-span UNSET form had zero preview hits) |
| Crashed agent shown as OK | root is OK while a child is ERROR | trace-level | `crashed_run_ok.py` |
| Duplicate model calls | the same response id/model appears on two LLM spans | trace-level | `duplicate_llm_calls.py` |
| Missing span | provider received a request but the trace contains no corresponding LLM span | not observable from one trace alone | Trueup's fake-provider comparison; no dashboard detection |
| Missing finish/tool detail | expected provider detail is absent from a span | requires request truth or library-specific attributes | Trueup's fake-provider comparison |

The installed group is `Trace truth (by Trueup)`. On 12 October the three conditional rules existed and fired:
output missing 25 times, successful-without-output 25 times, and zero-token LLM 6 times over the 30-day trend.
The counts include earlier project traces; 12 October contains four, four, and six hits
respectively.

Persisted demo evidence:

- Neatlogs session `demo-neatlogs-20261012T015515Z`: traces `7ecadf2e0debe934e325f0e8814815b2`,
  `6041090c2877aa7d78861796ee052fcb`, and `138533163e28239ec9181a42f7a7f899`.
- OpenInference session `demo-openinference-20261012T015747Z`: traces `c874896c638944221ea13d90494c3a56`,
  `fbcb88f7e7564fb32c76273111c5ceb0`, and `35a7fc38358b72dda5734a3567395c31`.
- OpenLLMetry ran and delivered nine spans through its OTLP exporter, but Neatlogs did not return them under the
  requested `demo-openllmetry-*` session. This is recorded as a session-grouping limitation, not a successful demo.

All demo calls used the local fake provider. The exporter is off by default and refuses to run without the explicit
flag; it prints its maximum span count before starting and aborts above 30 spans.
