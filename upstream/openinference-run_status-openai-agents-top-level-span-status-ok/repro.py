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
