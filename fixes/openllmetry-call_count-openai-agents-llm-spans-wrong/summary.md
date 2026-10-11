# openllmetry-call_count-openai-agents-llm-spans-wrong

openllmetry, openai-agents: LLM spans recorded wrong

Library commit: df4921a40940cdce136c4409380a55e9d4c7a96d. Located with ripgrep + ast (fallback).
Model: claude-sonnet-4.6; cost $0.649829 (key spend delta); run 20261011T010426Z-fix-openllmetry.

Result: fixed: the new test fails before and passes after, the suites show no new failure, the finding's scenarios match truth and the full scenario library has no new mismatch.

## Tries

1. FAIL at verify: still wrong after the patch: ag-bad-tool, ag-llm-fails, ag-max-turns, ag-run, ag-tool-raises. With the patch installed and the real scenario run, LLM spans: ag-bad-tool: truth 1 (provider requests), trace 2; ag-llm-fails: truth 2 (provider requests), trace 4; ag-max-turns: truth 3 (provider requests), trace 6; ag-run: truth 2 (provider requests), trace 4; ag-tool-raises: truth 2 (provider requests), trace 4. Spans exported with the patch ([name, status, description, parent]): ag-bad-tool: [['openai.response', 'UNSET', '', 'openai.response'], ['openai.response', 'OK', '', 'helper.agent'], ['helper.agent', 'OK', '', 'Agent Workflow'], ['Agent Workflow', 'OK', '', None]]; ag-llm-fails: [['op...
   Model's explanation: When the openai-agents instrumentation starts a generation/response span it attaches that span as the current OTel context. The openai instrumentation's responses_get_or_create_wrapper then also fires for the same underlying API call and creates a second openai.response span, doubling the LLM span count. The fix is to attach SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY=True to the context when starting a generation/response span in the agents processor (exactly like LangChain and LiteLLM do), ...
2. FAIL at verify: packages/opentelemetry-instrumentation-openai-agents: 1 test(s) fail in the full suite after the patch and did not fail before: .trueup.clones.openllmetry.packages.opentelemetry-instrumentation-openai-agents.tests.test_trueup_llm_span_count.TestResponsesWrapperSuppression::test_async_wrapper_suppressed_when_key_set. Output: est_async_wrapper_suppressed_when_key_set
    asyncio.get_event_loop().run_until_complete(run())
    ^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.12/asyncio/events.py:702: in get_event_loop
    raise RuntimeError('There is no current event loop in thread %r.'
E   RuntimeError: There is no current event loop in thread 'MainThread'.
- generated xml file: .trueu...
   Model's explanation: The responses_get_or_create_wrapper (and its async counterpart) only checks _SUPPRESS_INSTRUMENTATION_KEY but not SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY. When the openai-agents processor sets SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY=True for a generation span, the openai instrumentation ignores it and still creates a duplicate span. The fix is to also check SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY in both sync and async wrappers, and also set that key in the agents processor when s...
3. PASS at verified: all 5 scenario(s) of the finding now match truth here
   Model's explanation: The responses_get_or_create_wrapper (and async counterpart) only checks _SUPPRESS_INSTRUMENTATION_KEY but not SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY. When the openai-agents processor sets that key for a generation span, the openai instrumentation ignores it and creates a duplicate span. Fix: check SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY in both wrappers, and set it in the agents processor when starting generation spans. The async test also needs to use pytest-asyncio or a fresh event...

## Before and after

| scenario | field | truth | before | after |
|---|---|---|---|---|
| ag-bad-tool | LLM spans | 1 (provider requests) | 2 | matches truth |
| ag-llm-fails | LLM spans | 2 (provider requests) | 4 | matches truth |
| ag-max-turns | LLM spans | 3 (provider requests) | 6 | matches truth |
| ag-run | LLM spans | 2 (provider requests) | 4 | matches truth |
| ag-tool-raises | LLM spans | 2 (provider requests) | 4 | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 32 | 22 | 10 |
| after | 57 | 0 | 27 | 17 | 10 |

