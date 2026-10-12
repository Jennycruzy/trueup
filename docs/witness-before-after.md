# Witness live result

These are real provider calls: Claude Haiku and the OpenAI Agents SDK through the event's LiteLLM endpoint. No
practice server was used. "After" means Trueup's proposed patches, not merged upstream fixes.

| Kind of break | neatlogs before | neatlogs after Trueup's proposed patches | Really |
|---|---|---|---|
| Connection cut mid-reply (Anthropic stream) | AI step SUCCESS; whole trace listed as success | AI step ERROR, with the exception | Stream cut; app raised `RemoteProtocolError` |
| Agent run fails (server refuses the model) | Agent workflow SUCCESS | Agent workflow ERROR | Run failed; app raised `PermissionDeniedError` |

**DISAGREE light: 2 before → 0 after.** Both "before" traces carry the red `TRACE DISAGREE` step; neither
"after" trace does.

- Cut, before: https://app.neatlogs.com/traces/5322259c536eae9651b3f0819bfade85
- Cut, after: https://app.neatlogs.com/traces/7304699be40a6194bafc2a45478bcd4f
- Agent, before: https://app.neatlogs.com/traces/a4074bff1ff4af7caa62e015cae9c3f5
- Agent, after: https://app.neatlogs.com/traces/83f710d188f00e206a8b2339e0560443

**No false alarms.** 20 normal real calls before the patches and 20 after (7 plain, 6 streamed, 6 with a tool, 1
async each): 0 disagreements. All of this traffic cost $0.0124.

## What "after" is

- The three proven neatlogs patches, applied together to neatlogs 1.4.26 (they fix the cut stream).
- OpenInference's OpenAI Agents processor from our pull request
  [Arize-ai/openinference#4024](https://github.com/Arize-ai/openinference/pull/4024) at `4352755`, with the
  maintainer's review suggestions applied. `neatlogs.init(instrumentations=["openai_agents"])` runs
  OpenInference's processor, so this one fix repairs the Agents record for neatlogs users and Arize users alike.

neatlogs also has its own OpenAI Agents recorder (`neatlogs.openai_agents_processor()`), with the same bug. We sent
the fix, with 6 tests (2 fail before, all pass after): issue
[neatlogs/neatlogs#206](https://github.com/neatlogs/neatlogs/issues/206), pull request
[#207](https://github.com/neatlogs/neatlogs/pull/207).

## What is still not perfect

- In the agent run, the AI step is marked ERROR but carries no error details (no exception event). Witness reports
  this as a note, not a disagreement: the record no longer says the opposite of what happened.
- An inner step that is also named "Agent workflow" still ends SUCCESS under the failed workflow.

## Why our first attempt stayed 2 → 2

An earlier run the same morning applied only the three neatlogs patches and reported 2 → 2. It was right not to
claim a fix. Three things were wrong, all now corrected and covered by tests:

1. **The test relay sent a broken reply.** It skipped the stream's `content_block_start`, so the app crashed on
   bad data instead of on a real cut. The relay now sends a well-formed partial reply, then cuts the connection.
2. **Witness was too strict.** It treated "ERROR without error details" as "OK". It now reports the status exactly
   as recorded and lists missing details as a note.
3. **The wrong library was patched for the agent case.** None of the three neatlogs patches touches the Agents
   path, because neatlogs uses OpenInference's code there. The fix is #4024.

Witness also counted its own `TRACE DISAGREE` step as part of the run, which turned one lie into two marks. That
is fixed too (`tests/test_witness.py`).

The earlier records are kept in `evidence/witness/before.json` (`earlier_run`) and `after.json`
(`earlier_attempt`).

## Run it yourself

```
python examples/shop_agent.py --break anthropic-cut   # or --break agent-fail
python examples/witness_normal.py                     # 20 normal calls
```

Both read `TRUEUP_MODEL_KEY`, `TRUEUP_MODEL_BASE_URL` and `NEATLOGS_API_KEY` from the environment. Everything the
demo prints about the record comes from Witness's own comparison, not from the script.
