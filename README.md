# Trueup Witness

**Your dashboard said OK. Your agent crashed. Trueup turns on the DISAGREE light.**

Aircraft use two readings and warn pilots when they disagree. AI teams usually trust one instrument: the tracing record. Witness independently watches provider traffic and compares what happened with what neatlogs recorded.

```python
import trueup.witness
trueup.witness.watch()
```

When the record is wrong, Witness adds a `TRACE DISAGREE` step to the same neatlogs trace. It records status, exceptions, stream completion, refusals, tool names and usage. It never sends prompt or reply text beyond what neatlogs already records, never raises into the application, and can be disabled with `TRUEUP_WITNESS=0`.

## Live result

| Real break | neatlogs before | After Trueup's proposed patches | Really |
|---|---|---|---|
| Anthropic stream cable cut | OK, no exception | ERROR, no exception | Crashed |
| OpenAI Agents server rejection | Workflow OK | Workflow OK | Crashed |

The light remained **2 → 2**. That negative result matters: the existing patches did not fully repair these production cases. Across 20 normal real calls, Witness raised **0** disagreements. The gate traffic cost **$0.00626780**.

[Live traces and method](docs/witness-before-after.md) · [Evidence page](docs/index.html) · [Build record](hackathon.md) · [cfo.ai plan](https://cfo.ai/s/a9JKll8UYmSHs7-F)

The offline lab separately contains 32 confirmed findings and five locally proven patches across neatlogs, OpenInference and OpenLLMetry. Proposed patches are not upstream fixes until merged.
