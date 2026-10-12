# neatlogs-output-openai-chat-create-output-text-missing

neatlogs, openai chat create: output text not recorded

Library commit: 202f8776ea7d0902a6cb085495c6bcb00c226f8e. Located with entire graph + seed symbols.
Model: claude-sonnet-4.6; cost $0.164551 (key spend delta); run 20261012T010406Z-fix-neatlogs.

Result: fixed: the new test fails before and passes after, the suites show no new failure, the finding's scenarios match truth and the full scenario library has no new mismatch.

## Tries

1. PASS at verified: all 1 scenario(s) of the finding now match truth here
   Model's explanation: In `ChoiceAccumulator.add_response`, when a chat completion message has `content=None` (as happens with a refusal response), the code skips recording any output text. The fix is to fall back to the `refusal` field on the message when `content` is `None`, so the refusal text is recorded as the assistant's output. This matches the OpenAI spec where a refusal is the assistant's response when it declines to answer.

## Before and after

| scenario | field | truth | before | after |
|---|---|---|---|---|
| oa-chat-refusal | output text | ? | matches truth | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 35 | 11 | 24 |
| after | 57 | 0 | 34 | 11 | 23 |

