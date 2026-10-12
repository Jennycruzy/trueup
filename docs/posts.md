# X drafts — owner posts

## 1 — the light

Your dashboard said OK. Your agent crashed.

Trueup Witness watches the provider wire independently, compares it with the tracing record, and writes TRACE DISAGREE into the same @neatlogs trace.

We reproduced two real trace lies. 20 normal real calls raised 0 false disagreements. #neatHack

## 2 — publish the failure

We applied all 3 of Trueup's proven @neatlogs patches together and reran the live failures.

Anthropic improved from OK to ERROR, but still missed the exception event. OpenAI Agents still showed an OK workflow.

DISAGREE light: 2 → 2. We are publishing the failure, not painting it green. #neatHack

## 3 — install

Two lines give your AI trace a second sensor:

`import trueup.witness`
`trueup.witness.watch()`

It watches status, exceptions, stream completion, refusals, tools and usage. It never changes your app's result. Gate traffic cost: $0.00626780. #neatHack @EntireHQ
