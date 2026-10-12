<!-- Posted 2026-10-12 as neatlogs/neatlogs#206 (issue) and #207 (pull request). -->

# fix(openai-agents): mark the workflow span ERROR when the run fails

## What

The processor remembers the first error per trace from a span whose failure ends the run, and
`on_trace_end` sets the workflow span to ERROR with that message. Two kinds of error are left out, because the
run carries on after them (the same rules the OpenInference maintainers asked for in #4024):

- errors inside a tool (a function span and everything nested under it, for example an agent used as a tool):
  the SDK hands those back to the model by default;
- handoff-span errors ("Multiple handoffs requested"): the SDK takes the first handoff and finishes the run.

## Files

- `neatlogs/openai_agents.py`
- `tests/unit/test_trueup_openai_agents_run_status.py`

## Test

6 new tests. Without the fix, 2 fail (model call fails; max turns exceeded) and 4 pass (normal run, tool error
handed back, agent-as-tool fails but the run succeeds, multiple handoffs). With the fix, all 6 pass.

## Suites

`tests/unit` on 1.4.26 with openai-agents 0.23.1: 534 passed, 4 skipped, 5 failed both before and after the
patch (the CrewAI prompt-fidelity tests need `python-dotenv`, and `test_google_finish_reason_value` needs
`google-genai`, neither installed in the test environment).

## Known limit

If a `max_turns` error handler recovers the run, the SDK has already marked the agent span ERROR, so the
workflow mirrors it (the same limit the OpenInference maintainer noted on #4024).
