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
