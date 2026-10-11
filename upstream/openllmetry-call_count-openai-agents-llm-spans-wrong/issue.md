<!-- Drafted by Trueup from recorded runs. Not posted. -->

# 🐛 Bug Report: OpenAI Agents SDK: every non-streamed model call is recorded as two LLM spans (calls and tokens doubled)

### Which component is this bug for?

OpenAI Instrumentation (the fix is in opentelemetry-instrumentation-openai-agents and opentelemetry-instrumentation-openai)

### 📜 Description

Trueup ran each case against a fake provider, so it knows what really happened, and compared that with the exported spans:

- `ag-run`: LLM spans should be 2 (provider requests), the trace has 4
- `ag-tool-raises`: LLM spans should be 2 (provider requests), the trace has 4
- `ag-llm-fails`: LLM spans should be 2 (provider requests), the trace has 4
- `ag-max-turns`: LLM spans should be 3 (provider requests), the trace has 6
- `ag-bad-tool`: LLM spans should be 1 (provider requests), the trace has 2

Affected: `ag-bad-tool`, `ag-llm-fails`, `ag-max-turns`, `ag-run`, `ag-tool-raises`.

Right today on the same code path: `ag-streamed`, `ag-streamed-error`, `ag-streamed-cut`.

Checked on: latest release and main df4921a409.

### 👟 Reproduction steps

Standalone, 27 lines, needs only the library and the SDK; no API key, no network:

```python
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
```

Output on the latest release:

```
Traceloop exporting traces to a custom exporter

Metrics are disabled
provider requests: 1; LLM spans: 2; output tokens on LLM spans: 14 (provider sent 7)
```

### 👍 Expected behavior

One LLM span per model call (OTel GenAI conventions), with the tokens the provider sent.

### 👎 Actual Behavior with Screenshots

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


### 🤖 Python Version

3.12.3

### 📃 Provide any additional context for the Bug.

Python 3.12.3, Linux x86_64. Versions: traceloop-sdk 0.62.4, opentelemetry-instrumentation-openai 0.62.4, opentelemetry-instrumentation-anthropic 0.62.4, opentelemetry-instrumentation-langchain 0.62.4, opentelemetry-instrumentation-openai-agents 0.62.4, openai 3.28.0, anthropic 1.13.0, opentelemetry-sdk 1.45.1, langchain-core 1.6.9, langchain-openai 1.7.0, langgraph 1.2.14, openai-agents 0.23.1.

### 👀 Have you spent some time to check if this bug has been raised before?

- [x] I checked and didn't find similar issue (searched issues and PRs in all states: `openai-agents duplicate spans` (0 hits, 2026-10-10); `duplicate spans` (29 hits, 2026-10-10))

### Are you willing to submit PR?

Yes I am willing to submit a PR!