# Trueup Witness

**Your dashboard said OK. Your agent crashed. Trueup turns on the DISAGREE light.**

**[Crash it yourself, live →](https://trueup.38-49-216-59.sslip.io)** Break a real AI bot with one click.

Every fix links to the Entire record of the session that made it: see fixes/<id>/PROVENANCE.md.

Planes warn pilots when two readings disagree. AI teams trust one instrument: the tracing record. Witness watches what really happened and compares it with what neatlogs recorded.

```python
import trueup.witness
trueup.witness.watch()
```

When the record is wrong, Witness adds a red `TRACE DISAGREE` step to the same neatlogs trace. It never sends prompt or reply text beyond what neatlogs already records, never breaks your app, and turns off with `TRUEUP_WITNESS=0`.

## Live result

Real Claude Haiku and OpenAI Agents calls, before and after Trueup's patches:

| Real break | neatlogs before | After Trueup's patches | Really |
|---|---|---|---|
| Connection cut mid-reply | AI step SUCCESS | AI step ERROR, with the error | Crashed |
| Agent run fails | Agent workflow SUCCESS | Agent workflow ERROR | Crashed |

DISAGREE light: **2 → 0**, and it stayed off on 40 normal real calls. "After" means proposed patches, not merged fixes. neatlogs runs Arize's code for OpenAI Agents, so that fix is [our pull request to Arize](https://github.com/Arize-ai/openinference/pull/4024), with their maintainer's changes. Our first try stayed 2 → 2: [why, and the traces](docs/witness-before-after.md).

## neatlogs' own email got it wrong

neatlogs' daily email said 6.2% of our runs failed. We checked all 81: 9 had crashed, **11.1%**. These were test runs we crashed on purpose, recorded by released neatlogs, Arize and Traceloop code. The tracing code missed the crashes; the email only added up what it was given. [Every run](docs/neatlogs-email.md).

[Evidence page](docs/index.html) · [Build record](hackathon.md) · [cfo.ai plan](https://cfo.ai/s/a9JKll8UYmSHs7-F)

Trueup's offline lab: 32 confirmed findings, five proven patches across neatlogs, OpenInference and OpenLLMetry.
