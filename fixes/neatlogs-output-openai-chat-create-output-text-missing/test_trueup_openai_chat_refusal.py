"""Regression test: refusal text is recorded as output when content is None."""

from types import SimpleNamespace

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.openai import wrap_openai_client


class _RefusalCompletions:
    """Fake completions resource that returns a refusal (content=None, refusal set)."""

    def create(self, **_kwargs):
        return SimpleNamespace(
            id="chatcmpl-refusal",
            model="gpt-4o",
            choices=[
                SimpleNamespace(
                    index=0,
                    message=SimpleNamespace(
                        role="assistant",
                        content=None,
                        refusal="I can't help with that.",
                        tool_calls=[],
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


def test_refusal_is_recorded_as_output_text():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_neatlogs_provider(provider)

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_RefusalCompletions())
    )
    wrapped = wrap_openai_client(client)

    wrapped.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Do something harmful"}],
    )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    attrs = span.attributes

    # The refusal must be recorded as the assistant output content
    assert attrs.get("neatlogs.llm.output_messages.0.content") == "I can't help with that."
    assert attrs.get("neatlogs.llm.output_messages.0.role") == "assistant"
