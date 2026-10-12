# Trueup Witness

Checks your AI agent's records against what really happened, and fixes the tracing code when they disagree.

[![CI](https://github.com/Jennycruzy/trueup/actions/workflows/ci.yml/badge.svg)](https://github.com/Jennycruzy/trueup/actions/workflows/ci.yml) · **[Live demo](https://trueup.38-49-216-59.sslip.io/demo)**

**Why.** The dashboard said OK; the agent had crashed. The tracing code that feeds the dashboard can record a crash as success.

## Install

```
git clone https://github.com/Jennycruzy/trueup && pip install ./trueup
```

## Quick start

```python
import trueup.witness
trueup.witness.watch()          # once, at start-up, before neatlogs.init()

with trueup.witness.run("order-1042") as run:   # one unit of work
    answer = agent.handle(order_id="1042")

run.disagreements   # [] when the record matches what really happened
```

`TRUEUP_WITNESS=0` turns it off.

## What you see in neatlogs

When the record is wrong, Witness adds a red `TRACE DISAGREE` step to that same record. It never adds prompt or reply text neatlogs lacks, and never breaks your app.

Real crashes:

| Real break | neatlogs before | After Trueup's fixes | Really |
|---|---|---|---|
| Connection cut mid-reply | AI step SUCCESS | AI step ERROR, with the error | Crashed |
| Agent run fails | Agent workflow SUCCESS | Agent workflow ERROR | Crashed |

**DISAGREE light: 2 → 0.** 40 normal calls, 0 false alarms. [Details](docs/witness-before-after.md).

neatlogs' own daily email said 6.2% of our test runs failed; really 11.1% had crashed, because the tracing code recorded crashes as success. [Every run](docs/neatlogs-email.md).

## How it works

1. Witness reads each AI call off the connection: status, errors, stream end.
2. It compares that with the step neatlogs recorded.
3. On disagreement, it adds `TRACE DISAGREE`.
4. Trueup's lab finds the faulty tracing code, writes a fix and proves it.

[More](docs/how-it-works.md)

## Fixes sent upstream

Proposed until merged: [Arize-ai/openinference#4024](https://github.com/Arize-ai/openinference/pull/4024) (reviewed by Arize's head of open source), [traceloop/openllmetry#4610](https://github.com/traceloop/openllmetry/pull/4610), [neatlogs/neatlogs#207](https://github.com/neatlogs/neatlogs/pull/207). neatlogs runs Arize's code for OpenAI Agents, so the Arize fix repairs both.

## Built with neatlogs, Entire and cfo.ai

- **[neatlogs](docs/built-with.md#neatlogs)**: records every run, Witness's step included.
- **[Entire](docs/built-with.md#entire)**: every fix links to the session that made it.
- **[cfo.ai](docs/built-with.md#cfoai)**: [the plan](https://cfo.ai/s/kVKIburWzn09Baoy), from measured costs.

## Docs

[Getting started](docs/getting-started.md) · [How it works](docs/how-it-works.md) · [Built with](docs/built-with.md) · [Before and after](docs/witness-before-after.md) · [neatlogs' email](docs/neatlogs-email.md) · [Known limits](docs/limits.md) · [Build log](hackathon.md)

## License

[MIT](LICENSE)
