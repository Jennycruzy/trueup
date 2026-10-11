# Locate re-run: openinference-run_status-openai-agents-top-level-span-status-ok

Method: entire graph (entire graph search, neighbors and impact). Clone commit c364180e5b.
Query: openai-agents tracing: top-level span status is OK in the span but really ERROR (app raised InternalServerError) (openinference, openai-agents: top-level span status is OK)

| patched function | file | graph rank | ripgrep + ast rank | among graph callers |
|---|---|---|---|---|
| OpenInferenceTracingProcessor.__init__ | python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py | not found | only its class, at 1 | no |
| OpenInferenceTracingProcessor.on_trace_end | python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py | 6 | 3 | no |
| OpenInferenceTracingProcessor.on_span_end | python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py | 2 | 4 | yes |

Graph found 2 of 3 patched functions, 1 in its top 3 (the ones followed up with neighbors and impact). Ranked first: no.

Graph top hits:

1. _get_span_status (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py, score 59.0535)
2. OpenInferenceTracingProcessor.on_span_end (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py, score 53.6482)
3. OpenAIAgentsInstrumentor._instrument (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/__init__.py, score 47.9475)
4. _RealtimeSessionState.on_error (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_realtime.py, score 45.0751)
5. OpenInferenceTracingProcessor.on_span_start (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py, score 0)
6. OpenInferenceTracingProcessor.on_trace_end (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py, score 0)
7. OpenInferenceTracingProcessor.on_trace_start (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py, score 0)
8. OpenInferenceTracingProcessor.force_flush (python/instrumentation/openinference-instrumentation-openai-agents/src/openinference/instrumentation/openai_agents/_processor.py, score 0)
