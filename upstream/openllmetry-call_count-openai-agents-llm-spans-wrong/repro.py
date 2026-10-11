"""OpenLLMetry + OpenAI Agents SDK: one model call is recorded as two LLM spans.
Needs traceloop-sdk and openai-agents. Offline: httpx.MockTransport answers. Leave OPENAI_API_KEY
unset so the Agents SDK's own exporter skips its upload."""
import asyncio

import httpx
from openai import AsyncOpenAI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from traceloop.sdk import Traceloop

exporter = InMemorySpanExporter()
Traceloop.init(app_name="repro", exporter=exporter, disable_batch=True, telemetry_enabled=False)
from agents import Agent, OpenAIResponsesModel, Runner  # noqa: E402

BODY = {"id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": "m",
        "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "Hello!", "annotations": []}]}],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
transport = httpx.MockTransport(lambda request: httpx.Response(200, json=BODY))
client = AsyncOpenAI(api_key="x", base_url="http://fake/v1", http_client=httpx.AsyncClient(transport=transport))
agent = Agent(name="helper", model=OpenAIResponsesModel("m", client))
asyncio.run(Runner.run(agent, "hi"))
llm = [s for s in exporter.get_finished_spans() if s.attributes.get("gen_ai.operation.name") == "chat"]
tokens = sum(s.attributes.get("gen_ai.usage.output_tokens", 0) for s in llm)
print(f"provider requests: 1; LLM spans: {len(llm)}; output tokens on LLM spans: {tokens} (provider sent 7)")
