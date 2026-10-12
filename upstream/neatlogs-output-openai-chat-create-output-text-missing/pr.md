<!-- Drafted by Trueup from recorded runs. Not posted. -->

# fix(openai): record refusal text as chat output

## What

Chat refusals keep the assistant text in `message.refusal` while `message.content` is null. `ChoiceAccumulator.add_response` now uses that refusal as output when content is absent.

## Files

- `neatlogs/core/choice_accumulator.py`
- `tests/unit/test_trueup_openai_chat_refusal.py`

## Test

new test: fails before (1 of 1 failing), passes after (1 passed).

Normal content, tool calls and streaming responses are unchanged.

## Suites

- `.` before the patch: 527 passed, 1 failing (tests.unit.test_google_finish_reason_value)
- `.`: same 1 failure(s) as before the patch

## Before and after

| check | expected | latest release | proposed patch |
|---|---|---|---|
| output text | I can't help with that. | None | matches expected |
The standalone repro from the issue, with this patch:

```
recorded output: I can't help with that.
```

Trueup, an AI agent using Claude Sonnet 4.6, found and drafted this patch. Code verification accepted it after 1 attempt(s); every attempt is recorded in tries.json.
