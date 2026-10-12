from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider

_current: contextvars.ContextVar["Run | None"] = contextvars.ContextVar("trueup_witness_run", default=None)
_installed = False
_lock = threading.Lock()


@dataclass
class Call:
    route: str
    status: int | None = None
    exception: str | None = None
    stream: bool = False
    stream_done: bool | None = None
    error_event: bool = False
    body: bytearray = field(default_factory=bytearray)
    overhead_us: float = 0.0


@dataclass
class Run:
    name: str
    calls: list[Call] = field(default_factory=list)
    spans: list[ReadableSpan] = field(default_factory=list)
    app_exception: str | None = None


class _Processor(SpanProcessor):
    def on_start(self, span: Any, parent_context: Any = None) -> None:  # noqa: ARG002
        return

    def on_end(self, span: ReadableSpan) -> None:
        active = _current.get()
        if active is not None:
            active.spans.append(span)

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
        return True


class _SyncStream:
    def __init__(self, inner: Any, call: Call) -> None:
        self.inner, self.call = inner, call

    def __iter__(self):
        try:
            for chunk in self.inner:
                _observe(chunk, self.call)
                yield chunk
        except Exception as error:
            self.call.exception = type(error).__name__
            self.call.stream_done = False
            raise

    def close(self) -> Any:
        return self.inner.close()


class _AsyncStream:
    def __init__(self, inner: Any, call: Call) -> None:
        self.inner, self.call = inner, call

    async def __aiter__(self):
        try:
            async for chunk in self.inner:
                _observe(chunk, self.call)
                yield chunk
        except Exception as error:
            self.call.exception = type(error).__name__
            self.call.stream_done = False
            raise

    async def aclose(self) -> Any:
        return await self.inner.aclose()


def _observe(chunk: bytes, call: Call) -> None:
    call.body.extend(chunk)
    compact = chunk.replace(b" ", b"")
    if b"data: [DONE]" in chunk or b'"type":"message_stop"' in compact or b'"type":"response.completed"' in compact:
        call.stream_done = True
    if b'"type":"error"' in compact or b'event: error' in chunk:
        call.error_event = True


def _provider_path(url: Any) -> bool:
    path = str(getattr(url, "path", url)).lower()
    return any(x in path for x in ("/chat/completions", "/responses", "/messages"))


def _patch_http(module: Any) -> None:
    if getattr(module.Client.send, "__trueup_witness__", False):
        return
    sync_original, async_original = module.Client.send, module.AsyncClient.send

    class SyncStream(module.SyncByteStream):
        def __init__(self, inner: Any, call: Call) -> None:
            self.inner, self.call = inner, call
        def __iter__(self):
            try:
                for chunk in self.inner:
                    _observe(chunk, self.call); yield chunk
            except Exception as error:
                self.call.exception = type(error).__name__; self.call.stream_done = False; raise
        def close(self) -> Any:
            return self.inner.close()

    class AsyncStream(module.AsyncByteStream):
        def __init__(self, inner: Any, call: Call) -> None:
            self.inner, self.call = inner, call
        async def __aiter__(self):
            try:
                async for chunk in self.inner:
                    _observe(chunk, self.call); yield chunk
            except Exception as error:
                self.call.exception = type(error).__name__; self.call.stream_done = False; raise
        async def aclose(self) -> Any:
            return await self.inner.aclose()

    def send(client: Any, request: Any, *args: Any, **kwargs: Any):
        active = _current.get()
        if active is None or not _provider_path(request.url):
            return sync_original(client, request, *args, **kwargs)
        start = time.perf_counter_ns()
        call = Call(route=str(request.url.path), stream=bool(kwargs.get("stream")))
        active.calls.append(call)
        try:
            response = sync_original(client, request, *args, **kwargs)
            call.status = response.status_code
            response.stream = SyncStream(response.stream, call)
            return response
        except Exception as error:
            call.exception = type(error).__name__
            raise
        finally:
            call.overhead_us += (time.perf_counter_ns() - start) / 1000

    async def asend(client: Any, request: Any, *args: Any, **kwargs: Any):
        active = _current.get()
        if active is None or not _provider_path(request.url):
            return await async_original(client, request, *args, **kwargs)
        start = time.perf_counter_ns()
        call = Call(route=str(request.url.path), stream=bool(kwargs.get("stream")))
        active.calls.append(call)
        try:
            response = await async_original(client, request, *args, **kwargs)
            call.status = response.status_code
            response.stream = AsyncStream(response.stream, call)
            return response
        except Exception as error:
            call.exception = type(error).__name__
            raise
        finally:
            call.overhead_us += (time.perf_counter_ns() - start) / 1000

    send.__trueup_witness__ = asend.__trueup_witness__ = True
    module.Client.send, module.AsyncClient.send = send, asend


def _attach(provider: Any) -> None:
    if isinstance(provider, TracerProvider) and not getattr(provider, "_trueup_witness", False):
        provider.add_span_processor(_Processor())
        provider._trueup_witness = True


def watch() -> bool:
    """Install Witness once. It fails open and can be disabled with TRUEUP_WITNESS=0."""
    global _installed
    if os.environ.get("TRUEUP_WITNESS", "1").lower() in ("0", "false", "no"):
        return False
    with _lock:
        if _installed:
            return True
        import httpx
        _patch_http(httpx)
        try:
            import httpx2
            _patch_http(httpx2)
        except ImportError:
            pass
        try:
            import neatlogs
            from neatlogs._wrap_utils import get_neatlogs_provider
            _attach(get_neatlogs_provider())
            original = neatlogs.init
            if not getattr(original, "__trueup_witness__", False):
                def init(*args: Any, **kwargs: Any):
                    result = original(*args, **kwargs)
                    _attach(get_neatlogs_provider())
                    return result
                init.__trueup_witness__ = True
                neatlogs.init = init
        except Exception:
            pass
        _installed = True
    return True


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def _llm_spans(spans: list[ReadableSpan]) -> list[ReadableSpan]:
    return [s for s in spans if _attrs(s).get("neatlogs.span.kind") == "llm"]


def _has_exception(span: ReadableSpan) -> bool:
    return any(getattr(e, "name", "") == "exception" for e in span.events)


def _truth(call: Call) -> dict[str, Any]:
    raw = bytes(call.body)
    events = []
    for match in re.finditer(rb"(?:^|\n)data:\s*([^\n]+)", raw):
        if match.group(1).strip() != b"[DONE]":
            try: events.append(json.loads(match.group(1)))
            except ValueError: pass
    if not events and raw:
        try: events = [json.loads(raw)]
        except ValueError: pass
    refusal, tools, usage = [], [], None
    for event in events:
        obj = event.get("response", event)
        usage = obj.get("usage") or event.get("usage") or usage
        for choice in event.get("choices", []):
            msg = choice.get("message") or choice.get("delta") or {}
            if msg.get("refusal"): refusal.append(msg["refusal"])
            tools += [x.get("function", {}).get("name") for x in msg.get("tool_calls", [])]
        for item in obj.get("output", []) or []:
            if item.get("type") in ("function_call", "tool_call"): tools.append(item.get("name"))
        for block in obj.get("content", []) or []:
            if block.get("type") == "tool_use": tools.append(block.get("name"))
    return {"error": bool(call.exception or (call.status or 0) >= 400 or call.error_event or call.stream_done is False),
            "refusal": tuple(x for x in refusal if x), "tools": tuple(x for x in tools if x), "usage": usage}


def _record(span: ReadableSpan) -> dict[str, Any]:
    a = _attrs(span)
    tool_names = tuple(v for k, v in sorted(a.items()) if re.fullmatch(r"neatlogs\.llm\.tool_calls\.\d+\.name", k))
    usage = None
    if a.get("neatlogs.llm.token_count.prompt") is not None:
        usage = {"prompt_tokens": a.get("neatlogs.llm.token_count.prompt"),
                 "completion_tokens": a.get("neatlogs.llm.token_count.completion")}
    refusals = tuple(v for k, v in a.items() if ".refusal" in k and isinstance(v, str) and v)
    return {"error": span.status.status_code.name == "ERROR" and _has_exception(span),
            "refusal": refusals, "tools": tool_names, "usage": usage}


def _mark(field: str, record: Any, really: Any, finding: str | None = None) -> None:
    try:
        import neatlogs
        attrs = {"field": str(field), "record": str(record), "really": str(really)}
        if finding: attrs["finding"] = finding
        with neatlogs.trace(name="TRACE DISAGREE", kind="TOOL", **attrs):
            pass
    except Exception:
        return


def _compare(active: Run) -> None:
    llm = _llm_spans(active.spans)
    for index, call in enumerate(active.calls):
        if index >= len(llm):
            _mark("span", "missing", "provider call completed")
            continue
        truth, record = _truth(call), _record(llm[index])
        if truth["error"] != record["error"]:
            finding = "neatlogs-call_status-anthropic-messages-stream-span-status-ok-no-exception-event" if "messages" in call.route else None
            _mark("call_status", "ERROR" if record["error"] else "OK", "ERROR" if truth["error"] else "OK", finding)
        for field in ("refusal", "tools"):
            if truth[field] and truth[field] != record[field]:
                _mark(field, record[field] or "missing", truth[field])
    if active.app_exception:
        roots = [s for s in active.spans if s.parent is None]
        if roots and all(s.status.status_code.name != "ERROR" for s in roots):
            _mark("run_status", "/".join(s.status.status_code.name for s in roots), f"ERROR ({active.app_exception})",
                  "neatlogs-run_status-openai-agents-top-level-span-status-ok")


@contextlib.contextmanager
def run(name: str) -> Iterator[Run]:
    """Group provider truth and tracing spans, then compare without affecting the app."""
    watch()
    active = Run(name=name)
    token = _current.set(active)
    try:
        yield active
    except Exception as error:
        active.app_exception = type(error).__name__
        raise
    finally:
        try: _compare(active)
        finally: _current.reset(token)
