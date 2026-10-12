# Trueup Witness

**Your dashboard said OK. Your agent crashed.** Trueup Witness checks your AI agent's records against what really happened, warns you inside neatlogs when they disagree, and fixes the tracing code that got it wrong.

### Why it matters

- **Proven live with real Claude calls:** 2 wrong records before Trueup's fixes, 0 after, and 0 false alarms in 40 normal calls.
- **neatlogs' own daily email said 6.2%** of our test runs failed; really 11.1% had crashed (test runs we crashed on purpose).
- **The fix we sent Arize was reviewed by their head of open source**, and neatlogs runs that same code for agents, so one fix repairs both.
- **Built with all three tools:** neatlogs recorded every run and caught our own agent's mistakes, Entire recorded how Trueup and its fixes were built, cfo.ai built the business plan from measured costs.

[![CI](https://github.com/Jennycruzy/trueup/actions/workflows/ci.yml/badge.svg)](https://github.com/Jennycruzy/trueup/actions/workflows/ci.yml)

## For judges, start here

- **[Live demo](https://trueup.38-49-216-59.sslip.io/demo)**: break a real AI bot yourself.
- **[Product site](https://trueup.38-49-216-59.sslip.io)**: what Trueup is, in one page.
- **neatlogs records, [before](https://app.neatlogs.com/traces/5322259c536eae9651b3f0819bfade85) and [after](https://app.neatlogs.com/traces/7304699be40a6194bafc2a45478bcd4f) the fix**: also shown step by step on the demo page.
- **[How neatlogs caught and fixed Trueup's own mistakes](docs/built-with.md#neatlogs)**.
- **[neatlogs' daily email said 6.2%; the truth was 11.1%](docs/neatlogs-email.md)**.
- **Fixes sent to the companies that make these tools**: [Arize](https://github.com/Arize-ai/openinference/pull/4024), [neatlogs](https://github.com/neatlogs/neatlogs/pull/207), [Traceloop](https://github.com/traceloop/openllmetry/pull/4610).
- **Entire**: [the session where Trueup's agent wrote its first fixes](https://entire.io/gh/Jennycruzy/trueup/commit/79210a45418246ceb95e2990d1c003b5fbc7b3d9) (checkpoint `01M4M8M1GSQ2BM1RX2JKDJHPD6`), [full build history](https://entire.io/gh/Jennycruzy/trueup), [how each fix was made](fixes/openinference-run_status-openai-agents-top-level-span-status-ok/PROVENANCE.md).
- **[Our mistake with Entire](hackathon.md#what-entire-recorded-and-what-it-did-not-12-oct-observed)**: 20 updates went unrecorded; we said so and faked nothing.
- **[Business plan in cfo.ai](https://cfo.ai/s/kVKIburWzn09Baoy)**, also [here](docs/business-plan.md).
- **[Fixes gallery](https://trueup.38-49-216-59.sslip.io/fixes)** · **[Build log](hackathon.md)**

## The result

| Real break | neatlogs before | After Trueup's fixes |
|---|---|---|
| Connection cut mid-reply | AI step SUCCESS | AI step ERROR, with the error |
| Agent run fails | Agent workflow SUCCESS | Agent workflow ERROR |

**DISAGREE light: 2 → 0.** [Details](docs/witness-before-after.md).

## Install

Python 3.12 or newer.

```
git clone https://github.com/Jennycruzy/trueup && pip install ./trueup
```

## Quick start

```python
import os

import trueup.witness
trueup.witness.watch()          # once, at start-up, before neatlogs.init()

import neatlogs
neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], instrumentations=["openai"])

with trueup.witness.run("order-1042") as run:   # one job your agent does
    answer = agent.handle(order_id="1042")      # your own agent call

print(run.disagreements)        # [] when the record matches what really happened
```

When the record is wrong, Witness adds a red `TRACE DISAGREE` step to that record. It never breaks your app. `TRUEUP_WITNESS=0` turns it off.

From the project folder:

```
uv run entire trueup --help                               # Trueup as an Entire command
uv run trueup audit examples/agent.py --library neatlogs  # check your own script safely
```

## How it works

1. Witness reads each AI call off the connection: did the call fail, did the reply finish.
2. It compares that with the step neatlogs recorded and flags any mismatch with `TRACE DISAGREE`.
3. Trueup's test lab finds the faulty tracing code, writes a fix and proves it.

## Docs

[Getting started](docs/getting-started.md) · [How it works](docs/how-it-works.md) · [Built with](docs/built-with.md) · [Before and after](docs/witness-before-after.md) · [Known limits](docs/limits.md)

## License

[MIT](LICENSE)
