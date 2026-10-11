"""Regression tests: messages.stream() errors must produce ERROR spans."""
from typing import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.anthropic import wrap_anthropic_client


class RemoteProtocolError(Exception):
    """Stand-in for httpcore.RemoteProtocolError."""


class APIStatusError(Exception):
    """Stand-in for anthropic.APIStatusError."""


class _FakeStream:
    def __init__(self, events, error):
        self._events = events
        self._error = error

    def __iter__(self) -> Iterator:
        yield from self._events
        raise self._error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeStreamManager:
    def __init__(self, events, error):
        self._stream = _FakeStream(events, error)

    def __enter__(self):
        return self._stream

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeMessages:
    def __init__(self, events, error):
        self._events = events
        self._error = error

    def create(self, **kwargs):
        raise NotImplementedError

    def stream(self, **kwargs):
        return _FakeStreamManager(self._events, self._error)


class _FakeClient:
    def __init__(self, events, error):
        self.messages = _FakeMessages(events, error)


def _make_provider():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_neatlogs_provider(provider)
    return provider, exporter


def test_stream_helper_cut_produces_error_span():
    """RemoteProtocolError raised during iteration must set span status ERROR."""
    provider, exporter = _make_provider()

    error = RemoteProtocolError("peer closed connection without sending complete message body")
    client = _FakeClient(events=[], error=error)
    wrap_anthropic_client(client)

    with pytest.raises(RemoteProtocolError):
        with client.messages.stream(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        ) as stream:
            for _ in stream:
                pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "anthropic.messages.create"
    assert span.status.status_code == StatusCode.ERROR, (
        f"Expected ERROR, got {span.status.status_code}"
    )


def test_stream_helper_error_event_produces_error_span():
    """APIStatusError raised during iteration must set span status ERROR."""
    provider, exporter = _make_provider()

    error = APIStatusError("Error code: 529 - overloaded")
    client = _FakeClient(events=[], error=error)
    wrap_anthropic_client(client)

    with pytest.raises(APIStatusError):
        with client.messages.stream(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        ) as stream:
            for _ in stream:
                pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "anthropic.messages.create"
    assert span.status.status_code == StatusCode.ERROR, (
        f"Expected ERROR, got {span.status.status_code}"
    )


class _SuccessStream:
    def __init__(self, events):
        self._events = events

    def __iter__(self):
        yield from self._events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _SuccessStreamManager:
    def __init__(self, events):
        self._stream = _SuccessStream(events)

    def __enter__(self):
        return self._stream

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _SuccessMessages:
    def create(self, **kwargs):
        raise NotImplementedError

    def stream(self, **kwargs):
        return _SuccessStreamManager([])


class _SuccessClient:
    def __init__(self):
        self.messages = _SuccessMessages()


def test_successful_stream_produces_ok_span():
    """A stream that completes without error must still produce an OK span."""
    provider, exporter = _make_provider()

    client = _SuccessClient()
    wrap_anthropic_client(client)

    with client.messages.stream(
        model="claude-3-5-haiku-20241022",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}],
    ) as stream:
        for _ in stream:
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "anthropic.messages.create"
    assert span.status.status_code == StatusCode.OK, (
        f"Expected OK, got {span.status.status_code}"
    )
