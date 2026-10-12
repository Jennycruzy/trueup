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

## Posted

- Post 3 (owner): https://x.com/jennyoliver57/status/2109546774025113763
- Thread, 4 posts (owner): https://x.com/jennyoliver57/status/2109652614459633672

## Thread images (docs/x/)

1. `1-arize-review.png`: Arize PR #4024 and the review by Arize's head of open source (GitHub screenshot, 12 Oct).
2. `2-light-out.png`: before/after from the neatlogs records (real Claude Haiku calls through the event's model key).
3. `3-neatlogs-pr.png`: neatlogs PR #207 (GitHub screenshot, 12 Oct).
4. `4-neatlogs-email.png`: the daily email (6.2%) next to the real crash rate (11.1%).
5. `5-entire-record.png`: the Entire record of the session that built the fixer (public page, 12 Oct).
6. `6-cfo-plan.png`: the cfo.ai plan (shared page, 12 Oct).
