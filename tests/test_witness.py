import asyncio
import contextlib
import os
import types

import pytest

from trueup.witness import core


class Event:
    def __init__(self, name): self.name = name


class Status:
    def __init__(self, name): self.status_code = types.SimpleNamespace(name=name)


class Span:
    def __init__(self, status="OK", attrs=None, parent=object(), events=()):
        self.status, self.attributes, self.parent, self.events = Status(status), attrs or {"neatlogs.span.kind": "llm"}, parent, [Event(x) for x in events]


def test_truth_signals_status_cut_error_refusal_tools_usage():
    c = core.Call("/messages", status=200, stream=True, stream_done=False, exception="RemoteProtocolError")
    core._observe(b'data: {"type":"error","error":{"message":"x"}}\n\n', c)
    assert core._truth(c)["error"]
    c2 = core.Call("/chat/completions", status=200)
    core._observe(b'{"usage":{"prompt_tokens":2,"completion_tokens":1},"choices":[{"message":{"refusal":"no","tool_calls":[{"function":{"name":"lookup"}}]}}]}', c2)
    assert core._truth(c2) == {"error": False, "refusal": ("no",), "tools": ("lookup",), "usage": {"prompt_tokens": 2, "completion_tokens": 1}}


def test_stream_done_sync_and_async_leave_bytes_unchanged():
    c = core.Call("/responses", stream=True, stream_done=False)
    source = [b'data: {"type":"response.completed"}\n\n', b'data: [DONE]\n\n']
    assert list(core._SyncStream(iter(source), c)) == source and c.stream_done is True
    class A:
        async def __aiter__(self):
            for x in source: yield x
        async def aclose(self): pass
    async def go():
        c2=core.Call("/responses",stream=True,stream_done=False); got=[]
        async for x in core._AsyncStream(A(),c2): got.append(x)
        return got,c2
    got,c2=asyncio.run(go()); assert got==source and c2.stream_done is True


def test_compare_marks_status_output_and_run(monkeypatch):
    marks=[]; monkeypatch.setattr(core,"_mark",lambda *a,**k: marks.append((a,k)))
    call=core.Call("/messages",status=200,stream=True,stream_done=False,exception="cut")
    active=core.Run("x",[call],[Span("OK"),Span("OK",{"x":1},parent=None)],"RuntimeError")
    core._compare(active)
    assert {x[0][0] for x in marks} == {"call_status","run_status"}


def test_disabled_and_run_preserves_exception(monkeypatch):
    monkeypatch.setenv("TRUEUP_WITNESS","0"); monkeypatch.setattr(core,"_installed",False)
    assert core.watch() is False
    monkeypatch.setattr(core,"watch",lambda: True); monkeypatch.setattr(core,"_compare",lambda x: None)
    with pytest.raises(ValueError):
        with core.run("x"): raise ValueError("same")


class Ctx:
    def __init__(self, span_id): self.span_id = span_id


def _span(sid, parent, status="OK", kind="agent", events=()):
    sp = Span(status, {"neatlogs.span.kind": kind}, parent=Ctx(parent) if parent else None, events=events)
    sp.context = Ctx(sid)
    return sp


def test_failed_run_under_the_apps_own_open_span_lights_up():
    # The app's own outer span (id 1) is still open when the run ends, so the workflow (2) is the top step.
    spans = [_span(4, 3, "ERROR", "llm", ("exception",)), _span(3, 2, "ERROR"), _span(2, 1, "OK", "workflow")]
    active = core.Run("x", [], spans, "NotFoundError")
    core._compare(active)
    assert [d["field"] for d in active.disagreements] == ["run_status"]
    assert active.disagreements[0]["record"] == "OK"


def test_failed_run_shown_as_error_stays_dark():
    spans = [_span(3, 2, "ERROR"), _span(2, 1, "ERROR", "workflow")]
    active = core.Run("x", [], spans, "NotFoundError")
    core._compare(active)
    assert active.disagreements == []


def test_cut_stream_shown_as_error_with_exception_stays_dark():
    call = core.Call("/v1/messages", status=200, stream=True, stream_done=False, exception="RemoteProtocolError")
    active = core.Run("x", [call], [_span(2, 1, "ERROR", "llm", ("exception",))], "RemoteProtocolError")
    core._compare(active)
    assert active.disagreements == []


def test_cut_stream_shown_as_ok_lights_up():
    call = core.Call("/v1/messages", status=200, stream=True, stream_done=False, exception="RemoteProtocolError")
    active = core.Run("x", [call], [_span(2, 1, "OK", "llm")], "RemoteProtocolError")
    core._compare(active)
    assert [d["field"] for d in active.disagreements] == ["call_status"]


def test_error_without_details_is_a_note_not_a_disagreement():
    call = core.Call("/v1/responses", status=403)
    active = core.Run("x", [call], [_span(2, 1, "ERROR", "llm")], "PermissionDeniedError")
    core._compare(active)
    assert active.disagreements == []
    assert [n["field"] for n in active.notes] == ["call_status"]


def test_witness_own_marks_are_not_compared():
    call = core.Call("/v1/messages", status=200, stream=True, stream_done=False, exception="RemoteProtocolError")
    mark = _span(9, 1, "UNSET", "tool"); mark.name = "TRACE DISAGREE"
    llm = _span(2, 1, "OK", "llm"); llm.name = "anthropic.messages.create"
    active = core.Run("x", [call], [llm, mark], "RemoteProtocolError")
    core._compare(active)
    assert [d["field"] for d in active.disagreements] == ["call_status"]


def test_a_mark_made_during_the_comparison_is_not_compared(monkeypatch):
    call = core.Call("/v1/messages", status=200, stream=True, stream_done=False, exception="RemoteProtocolError")
    llm = _span(2, 1, "OK", "llm"); llm.name = "anthropic.messages.create"
    active = core.Run("x", [call], [llm], "RemoteProtocolError")
    real_mark = core._mark
    def mark_and_end_a_span(*a, **k):
        real_mark(*a, **k)
        m = _span(9, 1, "UNSET", "tool"); m.name = "TRACE DISAGREE"; active.spans.append(m)
    monkeypatch.setattr(core, "_mark", mark_and_end_a_span)
    core._compare(active)
    assert [d["field"] for d in active.disagreements] == ["call_status"]
