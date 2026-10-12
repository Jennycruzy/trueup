"""Trueup: openai responses stream error event sets ERROR span status."""

from types import SimpleNamespace
from typing import Iterator, List

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.openai import wrap_openai_client


def _setup_provider():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_neatlogs_provider(provider)
    return exporter


class _FakeResponsesStream:
    """Iterable that yields the given events then stops (no SDK exception)."""

    def __init__(self, events: List):
        self._events = iter(events)

    def __iter__(self) -> Iterator:
        return self

    def __next__(self):
        return next(self._events)


class _FakeResponses:
    def __init__(self, events: List):
        self._events = events

    def create(self, **kwargs):
        return _FakeResponsesStream(list(self._events))


def test_responses_stream_error_event_sets_error_span_status():
    """
    Scenario oa-resp-stream-error-event: the Responses API stream delivers a
    response.error event without raising in the SDK. The app then raises
    RuntimeError after consuming the stream. The span must be ERROR.
    """
    exporter = _setup_provider()

    error_msg = "fake stream error"
    events = [
        SimpleNamespace(type="response.created", response=None),
        # This is the terminal error event — no SDK exception is raised
        SimpleNamespace(type="response.error", message=error_msg, code="server_error"),
    ]

    client = SimpleNamespace(responses=_FakeResponses(events))
    wrapped = wrap_openai_client(client)

    stream = wrapped.responses.create(model="gpt-4o", input="hello", stream=True)
    # Consume the stream fully (the SDK does not raise; the app may raise afterward)
    consumed = list(stream)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1, f"Expected 1 span, got {len(spans)}: {spans}"
    span = spans[0]
    assert span.name == "openai.responses.create"
    assert span.status.status_code == StatusCode.ERROR, (
        f"Expected ERROR status but got {span.status.status_code}; "
        f"description={span.status.description!r}"
    )


def test_responses_stream_no_error_event_sets_ok_span_status():
    """A normal responses stream without any error event must produce an OK span."""
    exporter = _setup_provider()

    events = [
        SimpleNamespace(type="response.created", response=None),
        SimpleNamespace(type="response.output_text.delta", delta="hello"),
        SimpleNamespace(
            type="response.done",
            response=SimpleNamespace(model="gpt-4o", usage=None, status="completed"),
        ),
    ]

    client = SimpleNamespace(responses=_FakeResponses(events))
    wrapped = wrap_openai_client(client)

    stream = wrapped.responses.create(model="gpt-4o", input="hello", stream=True)
    list(stream)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.OK, (
        f"Expected OK status but got {span.status.status_code}"
    )
