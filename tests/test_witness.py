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
