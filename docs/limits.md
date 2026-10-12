# Known limits

What Trueup does not do yet.

- **No upstream fix is merged yet.** [Arize-ai/openinference#4024](https://github.com/Arize-ai/openinference/pull/4024),
  [traceloop/openllmetry#4610](https://github.com/traceloop/openllmetry/pull/4610) and
  [neatlogs/neatlogs#207](https://github.com/neatlogs/neatlogs/pull/207) are proposed. The "after" results use
  Trueup's proposed fixes, not released versions.
- **Witness reads OpenAI and Anthropic calls made through their Python SDKs**, which talk over httpx. Calls made
  another way (another language or another HTTP library) are not seen.
- **In the failed agent run, the AI step is now ERROR but has no error details.** Witness lists this as a note,
  not a disagreement: the record no longer says the opposite of what happened. An inner step that is also named
  "Agent workflow" still ends SUCCESS.
- **Tested with neatlogs as the dashboard.** Witness reads the steps neatlogs records. Other dashboards have not
  been tried.
- **Our first live attempt stayed 2 → 2.** It applied only the three neatlogs fixes; the test relay sent a broken
  reply, Witness was too strict, and the agent case needed the OpenInference fix instead. All three were corrected
  before the 2 → 0 run. [The full story](witness-before-after.md#why-our-first-attempt-stayed-2--2).
