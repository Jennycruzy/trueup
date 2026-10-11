# Locate re-run: openllmetry-call_count-openai-agents-llm-spans-wrong

Method: entire graph (entire graph search, neighbors and impact). Clone commit df4921a409.
Query: openai-agents tracing: LLM spans is 4 in the span but really 2 (provider requests) (openllmetry, openai-agents: LLM spans recorded wrong)

| patched function | file | graph rank | ripgrep + ast rank | among graph callers |
|---|---|---|---|---|
| OpenTelemetryTracingProcessor.__init__ | packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_hooks.py | not found | only its class, at 1 | no |
| OpenTelemetryTracingProcessor.on_span_start | packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_hooks.py | not found | 2 | yes |
| OpenTelemetryTracingProcessor.on_span_end | packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_hooks.py | not found | 3 | no |
| responses_get_or_create_wrapper | packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/v1/responses_wrappers.py | 6 | 4 | no |
| async_responses_get_or_create_wrapper | packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/v1/responses_wrappers.py | not found | 5 | no |

Graph found 1 of 5 patched functions, 0 in its top 3 (the ones followed up with neighbors and impact). Ranked first: no.

Graph top hits:

1. RealtimeTracingState.create_llm_span (packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_realtime_wrappers.py, score 38.5272)
2. RealtimeTracingState._get_parent_context (packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_realtime_wrappers.py, score 38.5172)
3. OpenTelemetryTracingProcessor._start_agent_span (packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/_hooks.py, score 34.5413)
4. OpenAIAgentsInstrumentor._instrument (packages/opentelemetry-instrumentation-openai-agents/opentelemetry/instrumentation/openai_agents/__init__.py, score 33.0033)
5. _record_traced_data (packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/v1/responses_wrappers.py, score 31.3923)
6. responses_get_or_create_wrapper (packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/v1/responses_wrappers.py, score 28.2531)
7. _set_span_attribute (packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/shared/__init__.py, score 28.0113)
8. RealtimeEventProcessor.start_response_span (packages/opentelemetry-instrumentation-openai/opentelemetry/instrumentation/openai/v1/realtime_wrappers.py, score 26.9869)
