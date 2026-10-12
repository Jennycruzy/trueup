# X drafts — owner posts

## 1 — the light

Your dashboard said OK. Your agent crashed.

Trueup Witness watches the provider wire independently, compares it with the tracing record, and writes TRACE DISAGREE into the same @neatlogs trace.

We reproduced two real trace lies. 20 normal real calls raised 0 false disagreements. #neatHack

## 2 — the light goes out

We cut the connection mid-reply and crashed an agent run, with real Claude calls. @neatlogs showed both as success.

Trueup found the causes, one in neatlogs' code and one in Arize's code that neatlogs uses for agents (our fix is under review: github.com/Arize-ai/openinference/pull/4024).

Same breaks with the fixes: both records say the run failed. DISAGREE light 2 → 0, and 0 false alarms on 40 normal calls. #neatHack

## 3 — install

Two lines give your AI trace a second sensor:

`import trueup.witness`
`trueup.witness.watch()`

It watches status, exceptions, stream completion, refusals, tools and usage. It never changes your app's result. Gate traffic cost: $0.00626780. #neatHack @EntireHQ
