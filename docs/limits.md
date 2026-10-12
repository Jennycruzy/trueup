# Known limits

What Trueup covers today, and where it stops.

- **All three fixes are sent and under review.** [Arize-ai/openinference#4024](https://github.com/Arize-ai/openinference/pull/4024),
  [traceloop/openllmetry#4610](https://github.com/traceloop/openllmetry/pull/4610) and
  [neatlogs/neatlogs#207](https://github.com/neatlogs/neatlogs/pull/207) are proposed; none is merged yet. The
  "after" results use Trueup's proposed fixes, not released versions.
- **Witness reads OpenAI and Anthropic calls made through their Python SDKs**, which talk over httpx. Calls made
  another way (another language or another HTTP library) are not seen.
- **In the failed agent run, the AI step is now ERROR but has no error details.** Witness lists this as a note,
  not a disagreement: the record no longer says the opposite of what happened. An inner step that is also named
  "Agent workflow" still ends SUCCESS.
- **Tested with neatlogs as the dashboard.** Witness reads the steps neatlogs records. Other dashboards have not
  been tried.
- **The live result is 2 → 0, and we show how we got there.** Our first live attempt stayed 2 → 2: it applied
  only the three neatlogs fixes; the test relay sent a broken reply, Witness was too strict, and the agent case
  needed the OpenInference fix instead. All three were corrected before the 2 → 0 run.
  [How we got there](witness-before-after.md#how-we-got-there).
