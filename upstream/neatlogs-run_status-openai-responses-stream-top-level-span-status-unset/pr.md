<!-- Drafted by Trueup from recorded runs. Not posted. -->

# fix(openai): record Responses stream error events

## What

The OpenAI SDK yields Responses error events instead of raising them. The stream finalizer now recognizes those events and records ERROR status plus an exception event.

## Files

- `neatlogs/openai.py`
- `tests/unit/test_trueup_responses_stream_error_event.py`

## Test

new test: fails before (1 of 2 failing), passes after (2 passed); guards (pass before, so they do not show the bug): test_responses_stream_no_error_event_sets_ok_span_status.

Normal completed streams remain OK; an interrupted stream without an error stays UNSET.

## Suites

- `.` before the patch: 527 passed, 1 failing (tests.unit.test_google_finish_reason_value)
- `.`: same 1 failure(s) as before the patch

## Before and after

| check | expected | latest release | proposed patch |
|---|---|---|---|
| top-level span status | ERROR (app raised RuntimeError) | UNSET | matches expected |
The standalone repro from the issue, with this patch:

```
span status: ERROR; exception events: 1
```

Trueup, an AI agent using Claude Sonnet 4.6, found and drafted this patch. Code verification accepted it after 2 attempt(s); every attempt is recorded in tries.json.
