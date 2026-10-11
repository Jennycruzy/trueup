<!-- Drafted by Trueup from recorded runs. Not posted. -->

# Anthropic messages.stream(): a stream that fails (error event or cut connection) is recorded as OK

## Symptom

Trueup ran each case against a fake provider, so it knows what really happened, and compared that with the exported spans:

- `p-an-stream-helper-cut`: top-level span status should be ERROR (app raised RemoteProtocolError), the trace has OK
- `p-an-stream-helper-error-event`: top-level span status should be ERROR (app raised APIStatusError), the trace has OK

## Boundary

Affected: `p-an-stream-helper-cut`, `p-an-stream-helper-error-event`.

Right today on the same code path: `p-an-async-stream-cut`, `p-an-async-stream-error`.

Checked on: latest release and main 202f8776ea.

## Repro

Standalone, 30 lines, needs only the library and the SDK; no API key, no network:

```python
"""neatlogs + Anthropic messages.stream(): a stream that fails leaves the span OK.
Needs neatlogs and anthropic. Offline: httpx.MockTransport answers with an SSE stream that ends in an
error event; export is off. anthropic 1.x uses httpx2 instead of httpx."""
import json

import anthropic
import httpx2 as httpx
import neatlogs
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter, provider = InMemorySpanExporter(), TracerProvider()
neatlogs.init(api_key="x", instrumentations=["anthropic"], disable_export=True, tracer_provider=provider)
provider.add_span_processor(SimpleSpanProcessor(exporter))
start = {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
         "content": [], "stop_reason": None, "usage": {"input_tokens": 5, "output_tokens": 0}}}
error = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in (start, error))
transport = httpx.MockTransport(lambda r: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}))
client = anthropic.Anthropic(api_key="x", base_url="http://fake", http_client=httpx.Client(transport=transport))
try:
    with client.messages.stream(model="m", max_tokens=16, messages=[{"role": "user", "content": "hi"}]) as s:
        "".join(s.text_stream)
except Exception as e:
    print(f"the app saw {type(e).__name__}")
neatlogs.flush()
for span in exporter.get_finished_spans():
    print(f"span {span.name!r}: {span.status.status_code.name}, exception events: "
          f"{sum(e.name == 'exception' for e in span.events)}")
```

Output on the latest release:

```
the app saw APIStatusError
span 'anthropic.messages.create': OK, exception events: 0
2026-10-11 01:14:44 - neatlogs - INFO - Neatlogs SDK shutdown complete
```

## Expected

The span is ERROR with an exception event, as neatlogs already records for messages.create(stream=True).

## Before and after the proposed fix

| scenario | field | truth | before | after |
|---|---|---|---|---|
| p-an-stream-helper-cut | top-level span status | ERROR (app raised RemoteProtocolError) | OK | matches truth |
| p-an-stream-helper-error-event | top-level span status | ERROR (app raised APIStatusError) | OK | matches truth |

Full scenario library for this library (same venv, before and after the patch):

| | scenarios ran | not run | leads | high | medium |
|---|---|---|---|---|---|
| before | 57 | 0 | 35 | 11 | 24 |
| after | 57 | 0 | 31 | 9 | 22 |


## Environment

Python 3.12.3, Linux x86_64. Versions: neatlogs 1.4.26, openinference-instrumentation-langchain 0.1.79, openinference-instrumentation-openai-agents 2.5.3, openai 3.28.0, anthropic 1.13.0, opentelemetry-sdk 1.45.1, langchain-core 1.6.9, langchain-openai 1.7.0, langgraph 1.2.14, openai-agents 0.23.1.

Searched issues and PRs first: `anthropic span status error stream` (0 hits, 2026-10-10); `span status error stream` (1 hits, 2026-10-10).