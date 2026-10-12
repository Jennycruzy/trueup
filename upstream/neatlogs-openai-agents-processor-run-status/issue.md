<!-- Drafted by hand from Trueup's findings. Not posted. -->

# OpenAI Agents: a failed run is recorded as OK by `openai_agents_processor()`

## Symptom

When an OpenAI Agents run fails (the model call returns an error, or `MaxTurnsExceeded`), `Runner.run` raises,
but the `openai_agents.trace` span (the workflow, the top line in the dashboard) ends with status OK. The
agent span below it is ERROR, so the failure is only visible if you open the trace and look inside.

## Cause

`_NeatlogsTraceProcessor.on_trace_end` always calls `span.set_status(StatusCode.OK)`.

## Repro

`tests/unit/test_trueup_openai_agents_run_status.py` in the attached patch: a scripted model that fails on its
second call, and an agent that loops until `MaxTurnsExceeded`. Both runs raise; both workflow spans end OK on
1.4.26.

## Note

`neatlogs.init(instrumentations=["openai_agents"])` uses OpenInference's processor instead, which has the
same problem; that one is under review upstream in Arize-ai/openinference#4024.
