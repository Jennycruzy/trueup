<!-- Drafted by Trueup from recorded runs. Not posted. -->

# [bug] openai-agents: a run that raises leaves the top-level span OK

**Describe the bug**

Trueup ran each case against a fake provider, so it knows what really happened, and compared that with the exported spans:

- `ag-llm-fails`: top-level span status should be ERROR (app raised InternalServerError), the trace has OK
- `ag-max-turns`: top-level span status should be ERROR (app raised MaxTurnsExceeded), the trace has OK
- `ag-bad-tool`: top-level span status should be ERROR (app raised ModelBehaviorError), the trace has OK
- `ag-streamed-error`: top-level span status should be ERROR (app raised ModelBehaviorError), the trace has OK
- `ag-streamed-cut`: top-level span status should be ERROR (app raised APIConnectionError), the trace has OK

Affected: `ag-bad-tool`, `ag-llm-fails`, `ag-max-turns`, `ag-streamed-cut`, `ag-streamed-error`.

Right today on the same code path: `ag-run`, `ag-tool-raises`, `ag-streamed`.

Checked on: latest release and main c364180e5b.

**To Reproduce**

Standalone, 28 lines, needs only the library and the SDK; no API key, no network:

```python
"""OpenInference + OpenAI Agents SDK: a run that raises leaves the top-level span OK.
Needs openinference-instrumentation-openai-agents and openai-agents. Offline: httpx.MockTransport
answers HTTP 500. Leave OPENAI_API_KEY unset so the Agents SDK's own exporter skips its upload."""
import asyncio

import httpx
from openai import AsyncOpenAI
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)
from agents import Agent, OpenAIResponsesModel, Runner  # noqa: E402

transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": {"message": "boom"}}))
client = AsyncOpenAI(api_key="x", base_url="http://fake/v1", max_retries=0,
                     http_client=httpx.AsyncClient(transport=transport))
agent = Agent(name="helper", model=OpenAIResponsesModel("m", client))
try:
    asyncio.run(Runner.run(agent, "hi"))
except Exception as e:
    print(f"the run raised {type(e).__name__}")
root = next(s for s in exporter.get_finished_spans() if s.parent is None)
print(f"top-level span {root.name!r}: {root.status.status_code.name}")
```

Output on the latest release:

```
the run raised InternalServerError
top-level span 'Agent workflow': OK
```

**Expected behavior**

The top-level span is ERROR when the run raises (a span whose operation failed has status ERROR). A run whose tool raised but which still finished stays OK.

**Screenshots**

None; the repro prints the span status.

**Environment**

Python 3.12.3, Linux x86_64. Versions: openinference-instrumentation-openai 0.1.65, openinference-instrumentation-anthropic 3.0.3, openinference-instrumentation-langchain 0.1.79, openinference-instrumentation-openai-agents 2.5.3, openai 3.28.0, anthropic 1.13.0, opentelemetry-sdk 1.45.1, langchain-core 1.6.9, langchain-openai 1.7.0, langgraph 1.2.14, openai-agents 0.23.1.

**Additional context**

Before and after the proposed fix, from Trueup's runs:

| scenario | field | truth | before | after |
|---|---|---|---|---|
| ag-bad-tool | top-level span status | ERROR (app raised ModelBehaviorError) | OK | matches truth |
| ag-llm-fails | top-level span status | ERROR (app raised InternalServerError) | OK | matches truth |
| ag-max-turns | top-level span status | ERROR (app raised MaxTurnsExceeded) | OK | matches truth |
| ag-streamed-cut | top-level span status | ERROR (app raised APIConnectionError) | OK | matches truth |
| ag-streamed-error | top-level span status | ERROR (app raised ModelBehaviorError) | OK | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 19 | 7 | 12 |
| after | 57 | 0 | 14 | 2 | 12 |

Searched issues and PRs first: `openai-agents span status error` (0 hits, 2026-10-10); `span status error` (30 hits, 2026-10-10).