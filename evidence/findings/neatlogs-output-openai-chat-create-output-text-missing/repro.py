"""neatlogs + OpenAI Chat Completions: refusal text is not recorded.
Offline: a small response object stands in for the provider; export is off."""
from types import SimpleNamespace as NS

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.openai import wrap_openai_client
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

class Completions:
    def create(self, **kwargs):
        message = NS(role="assistant", content=None, refusal="I can't help with that.", tool_calls=[])
        return NS(id="r1", model="m", choices=[NS(index=0, message=message, finish_reason="stop")], usage=None)

exporter, provider = InMemorySpanExporter(), TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
set_neatlogs_provider(provider)
client = wrap_openai_client(NS(chat=NS(completions=Completions())))
client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
span = exporter.get_finished_spans()[0]
print("recorded output:", span.attributes.get("neatlogs.llm.output_messages.0.content"))
