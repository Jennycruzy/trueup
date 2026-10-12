# Getting started

## Install

Python 3.12 or newer.

```
git clone https://github.com/Jennycruzy/trueup
pip install ./trueup
```

To run the demo agents and the tests as well, install the development extras with [uv](https://docs.astral.sh/uv/):

```
cd trueup && uv sync
```

## Quick start

Call `watch()` once at start-up, before `neatlogs.init()`. Then wrap each unit of work in `run()`.

```python
import os

import trueup.witness
trueup.witness.watch()          # once, at start-up, before neatlogs.init()

import neatlogs
neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], instrumentations=["openai"])

with neatlogs.trace(name="shop-agent", kind="AGENT"):
    try:
        with trueup.witness.run("order-1042") as run:   # one unit of work
            answer = agent.handle(order_id="1042")
    except Exception:
        pass                    # your app's own error handling; Witness never swallows an error

print(run.disagreements)        # [] when the record matches what really happened
print(run.notes)                # smaller gaps that do not turn the light on
```

- `run()` gives you the run as soon as it starts. `run.disagreements` and `run.notes` are filled in when the
  `with` block ends, including when your code raised.
- Each disagreement is a small dictionary: `field` (what was compared), `record` (what neatlogs recorded),
  `really` (what really happened) and, when Trueup knows the cause, `finding` (the matching Trueup finding).
- Witness never changes what your app sends or receives, and if Witness itself fails, your app carries on.

## Reading the TRACE DISAGREE step in neatlogs

When the record and reality disagree, Witness adds a red step named `TRACE DISAGREE` to the same neatlogs record,
next to the step that is wrong. Its fields say what was compared:

| field | meaning |
|---|---|
| `call_status` | One AI call: neatlogs says SUCCESS (or ERROR), but the call really failed (or succeeded). |
| `run_status` | The whole run: your code raised, but every top step in the record says SUCCESS. |
| `refusal` | The AI refused, but the refusal is missing from the record. |
| `tools` | The AI asked for tools, but the record names different tools or none. |

A missing AI step (the call happened, the record has no step for it) is also reported, with `record` set to
`missing`.

## The neatlogs detection to create

So that you hear about a disagreement without opening each record:

1. In neatlogs, open **Detections** and create a conditional detection that matches steps named
   `TRACE DISAGREE`. Call it `TRACE DISAGREE light`.
2. Open **Alerts** and add a rule for that detection: at least one occurrence. Pick where it should notify you.

## Turning it off

```
export TRUEUP_WITNESS=0
```

`watch()` then does nothing and returns `False`; `run()` still works but has nothing to compare.

## Running the demo agent

`examples/shop_agent.py` is a small shop agent that can be broken on purpose. It uses real AI calls, so it needs
three settings in the environment: `TRUEUP_MODEL_KEY`, `TRUEUP_MODEL_BASE_URL` (an OpenAI-compatible address)
and `NEATLOGS_API_KEY`.

```
uv run python examples/shop_agent.py                        # a normal call: the light stays off
uv run python examples/shop_agent.py --break anthropic-cut  # the connection is cut mid-reply
uv run python examples/shop_agent.py --break agent-fail     # an OpenAI Agents run fails
uv run python examples/witness_normal.py                    # 20 normal calls; expect 0 disagreements
```

Every line the demo prints about the record comes from Witness's own comparison. `--json-out FILE` saves the
verdict. Run either script with `--help` to see its options.

## Checking your own script against the practice AI server

`trueup audit` runs your script's `main()` against Trueup's practice AI server: a local stand-in for OpenAI and
Anthropic that fails on purpose (errors, cut connections, refusals, tool calls). It then compares what really
happened with what the tracing library recorded. No keys are needed.

```
uv run trueup audit examples/agent.py --library neatlogs
```

`--library` is `neatlogs`, `openinference` or `openllmetry`. Your `main()` must take no arguments and call the
`openai` or `anthropic` SDK with a client that reads `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` (the default). The
first run prepares a separate environment for the library, so it takes a little longer. On `examples/agent.py`
with neatlogs it finds one gap: a refusal that was not recorded.

## Checking Trueup's own numbers

```
uv run trueup verify    # recomputes every number from evidence/ and checks every file's checksum
uv run trueup demo      # replays one finding from start to finish, offline
```
