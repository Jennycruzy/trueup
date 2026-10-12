# How it works

Trueup has two parts. **Witness** runs inside your app and turns on a light when the record is wrong. **The lab**
runs on a developer's machine, finds out why the record is wrong, and writes and proves the fix.

## Witness

### What it reads

`watch()` hooks into httpx, the HTTP library that the OpenAI and Anthropic Python SDKs use to talk to their
servers. Inside a `run()`, for every call to a chat, responses or messages address, it notes:

- the HTTP status and any connection error;
- for streamed replies, whether the stream reached its proper end (`[DONE]`, `message_stop` or
  `response.completed`) or was cut off, and whether the server sent an error event part-way;
- refusals and the names of the tools the AI asked for.

Bytes pass straight through to your app unchanged. The added time per call was 2.9005 microseconds at the
median (4.809 at most) in the live run.

### What it compares

`watch()` also attaches a listener to neatlogs, so every step neatlogs records during a `run()` is copied to
Witness as well. When the run ends, Witness lines up each real AI call with the matching AI step in the record and
asks:

1. **Did it fail?** The call failed (error status, connection error, error event, or a cut stream) but the step
   says SUCCESS, or the other way round.
2. **Did the whole run fail?** Your code raised, but every top step in the record still says SUCCESS.
3. **Refusal and tools.** The AI refused or asked for tools, and the record says something else.
4. **Is the step there at all?** A call happened with no AI step for it.

### When the light turns on

Any "no" above is a **disagreement**: the record says the opposite of what happened. Witness adds a red
`TRACE DISAGREE` step to the same neatlogs record and adds the disagreement to `run.disagreements`.

### Notes

Some gaps are real but do not make the record say the opposite of what happened. Example: the step is correctly
marked ERROR but carries no error details. Witness lists these in `run.notes` and leaves the light off. Witness's
own `TRACE DISAGREE` steps are never compared, so one wrong record gives one mark, not two.

## The lab

### Practice AI server

A local server that answers like OpenAI (chat and responses) and Anthropic (messages), and fails on purpose:
server errors, connections cut mid-reply, error events in a stream, refusals, tool calls, agents that hit their
step limit. It keeps its own log of exactly what it sent. Trueup ships 51 of these test cases and runs them
against neatlogs, OpenInference (Arize) and OpenLLMetry (Traceloop).

### Comparison

For each case, Trueup compares what really happened (the server's log and whether the app raised) with what the
tracing library recorded. Every difference is a possible problem.

### Checker rules

A possible problem becomes a confirmed **finding** only if it passes seven rules:

1. It happens twice in a row, each time in a fresh process.
2. It happens with the library's recommended setup.
3. It happens on the latest release and on the library's main branch.
4. The practice server really sent what Trueup says it sent.
5. The test itself is sound (no shared state, nothing sent anywhere).
6. Another library, or the published OpenTelemetry conventions (the shared standard for these records), shows
   the right behaviour.
7. A script under 40 lines shows it on its own.

Anything that fails a rule is set aside with the reason, never deleted. The result so far: 32 confirmed findings
across the three libraries.

### Fixer

For a finding, Trueup clones the library, finds the code most likely at fault, and asks a model for a small
change plus one new test. Code, not the model, rejects edits outside the library, in its tests, or that do not
compile.

### Verifier

A fix counts only if:

- the new test fails before the change and passes after;
- the library's own test suite shows no new failure;
- the finding's test cases now match what really happened;
- all test cases together show no new difference.

Up to three tries per run; a failed try goes back to the model with the reason. Five fixes have passed so far.

### Upstream drafts

`trueup upstream` writes the issue and pull-request text for a proven fix into `upstream/`. It never posts.
A person re-checks the latest release, main and open pull requests, then posts. Three have been posted:
[Arize-ai/openinference#4024](https://github.com/Arize-ai/openinference/pull/4024),
[traceloop/openllmetry#4610](https://github.com/traceloop/openllmetry/pull/4610) and
[neatlogs/neatlogs#207](https://github.com/neatlogs/neatlogs/pull/207).

### Checking the numbers

`uv run trueup verify` recomputes every number above from `evidence/` and checks every file's checksum.
