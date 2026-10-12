"""neatlogs + OpenAI Responses: a terminal error event leaves the span UNSET.
Offline: a small event iterator stands in for the provider; export is off."""
from types import SimpleNamespace as NS

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.openai import wrap_openai_client
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

class Responses:
    def create(self, **kwargs):
        return iter([NS(type="response.created", response=None),
                     NS(type="error", message="server failed", code="server_error")])

exporter, provider = InMemorySpanExporter(), TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
set_neatlogs_provider(provider)
client = wrap_openai_client(NS(responses=Responses()))
list(client.responses.create(model="m", input="hi", stream=True))
span = exporter.get_finished_spans()[0]
errors = sum(event.name == "exception" for event in span.events)
print(f"span status: {span.status.status_code.name}; exception events: {errors}")
