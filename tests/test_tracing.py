import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from trueup import tracing
from trueup.runner.run import SRC, child_env

FAKE_NEATLOGS = textwrap.dedent('''
    import contextlib, os
    LOG = os.environ["FAKE_NEATLOGS_LOG"]
    def _w(s):
        with open(LOG, "a") as f:
            f.write(s + "\\n")
    def init(**kw):
        _w("init " + ",".join(sorted(kw)) + " " + " ".join(kw["tags"]) + " " + ",".join(kw["instrumentations"]))
    def flush(*a, **k):
        _w("flush")
        return True
    @contextlib.contextmanager
    def trace(name, **kw):
        _w("trace " + name + " session=" + kw["session_id"] + " lib=" + kw["trueup.library"])
        yield None
''')


@pytest.fixture
def fake_neatlogs(tmp_path, monkeypatch):
    (tmp_path / "neatlogs.py").write_text(FAKE_NEATLOGS)
    log = tmp_path / "log.txt"
    monkeypatch.setenv("FAKE_NEATLOGS_LOG", str(log))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "neatlogs", raising=False)
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-secret")
    yield log
    tracing._state.update(active=False, flushed=True)


def test_without_key_runs_untraced_and_says_so_once(monkeypatch):
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    lines = []
    assert tracing.start("r1", "neatlogs", "plan", lines.append) is False
    assert lines == ["NEATLOGS_API_KEY is not set: running without neatlogs tracing"]
    with tracing.worker("trueup-planner") as span:
        assert span is None
    tracing.flush()


def test_one_session_tags_and_worker_names(fake_neatlogs):
    lines = []
    tracing.start("r1", "openllmetry", "plan", lines.append)
    with tracing.worker("trueup-planner"):
        pass
    with tracing.worker("trueup-runner"):
        pass
    with tracing.worker("trueup-reporter"):
        pass
    tracing.flush()
    tracing.flush()
    log = fake_neatlogs.read_text().splitlines()
    assert log[0].startswith("init api_key,") and "run_id:r1 library:openllmetry trueup:" in log[0]
    assert log[0].endswith(" openai")
    assert log[1:] == ["trace trueup-planner session=r1 lib=openllmetry",
                       "trace trueup-runner session=r1 lib=openllmetry",
                       "trace trueup-reporter session=r1 lib=openllmetry", "flush"]
    assert "nl-secret" not in "\n".join(lines)
    with pytest.raises(ValueError):
        with tracing.worker("trueup-dancer"):
            pass


def test_flush_on_crash_in_process(fake_neatlogs):
    def body():
        raise RuntimeError("worker crashed")
    with pytest.raises(RuntimeError):
        tracing.run_traced("r2", "neatlogs", "plan", body, out=lambda s: None)
    assert fake_neatlogs.read_text().splitlines()[-1] == "flush"


def test_flush_records_failed_delivery(fake_neatlogs, monkeypatch, capsys):
    import neatlogs

    tracing.start("r-failed", "neatlogs", "verify", out=lambda _: None)
    monkeypatch.setattr(neatlogs, "flush", lambda: False)
    assert tracing.flush() is False
    assert tracing.delivery() == "failed"
    assert "did not confirm trace delivery" in capsys.readouterr().err


def test_flush_on_uncaught_crash_in_subprocess(tmp_path):
    (tmp_path / "neatlogs.py").write_text(FAKE_NEATLOGS)
    log = tmp_path / "log.txt"
    code = ("from trueup import tracing\n"
            "tracing.start('r3', 'neatlogs', 'plan')\n"
            "1 / 0\n")
    env = {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{SRC}", "FAKE_NEATLOGS_LOG": str(log),
           "NEATLOGS_API_KEY": "nl-secret"}
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert p.returncode == 1 and "ZeroDivisionError" in p.stderr
    assert log.read_text().splitlines()[-1] == "flush"  # atexit flushed after the crash
    assert "nl-secret" not in p.stdout + p.stderr


def test_inner_capture_env_while_outer_tracing_is_on(fake_neatlogs, monkeypatch):
    monkeypatch.setenv("NEATLOGS_ENDPOINT", "https://ingest.example")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.example")
    tracing.start("r4", "neatlogs", "plan", lambda s: None)
    env = child_env()
    for k in ("NEATLOGS_API_KEY", "NEATLOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        assert k not in env, k
    assert env["NEATLOGS_DISABLE_EXPORT"] == "true"
    assert env["OTEL_TRACES_EXPORTER"] == env["OTEL_LOGS_EXPORTER"] == "none"


# A sitecustomize that records every non-loopback connection the child tries.
GUARD = textwrap.dedent('''
    import os, socket
    _orig = socket.socket.connect
    def connect(self, addr):
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
            with open(os.environ["TRUEUP_NET_LOG"], "a") as f:
                f.write(f"{host}\\n")
        return _orig(self, addr)
    socket.socket.connect = connect
''')


@pytest.mark.e2e
def test_inner_spans_never_leave_the_machine(tmp_path, monkeypatch):
    from trueup.runner import venvs

    root = Path(__file__).resolve().parents[1]
    python = venvs.ensure(root, "neatlogs")
    (tmp_path / "sitecustomize.py").write_text(GUARD)
    net = tmp_path / "net.txt"
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-fake-outer-key")  # as if outer tracing were on
    env = child_env()
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{SRC}"
    env["TRUEUP_NET_LOG"] = str(net)
    out = tmp_path / "obs.json"
    p = subprocess.run([str(python), "-m", "trueup.runner.child", "neatlogs", "oa-chat-plain", str(out)],
                       env=env, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert out.exists(), p.stderr[-2000:]
    import json
    payload = json.loads(out.read_text())
    assert payload["ok"] and payload["observation"]["trace"]["spans"]  # spans were captured in memory
    assert not net.exists() or net.read_text() == "", net.read_text()


def test_verdict_and_labels_go_where_neatlogs_reads_them(monkeypatch):
    # neatlogs drops unknown span attributes from its view; detections see output.value and metadata.
    import contextlib
    import json
    import types

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    tracer = provider.get_tracer("t")

    @contextlib.contextmanager
    def trace(name, **kw):
        with tracer.start_as_current_span(name) as span:
            yield span

    monkeypatch.setitem(sys.modules, "neatlogs", types.SimpleNamespace(trace=trace, flush=lambda: True))
    monkeypatch.setitem(tracing._state, "active", True)
    monkeypatch.setitem(tracing._state, "run_id", "r1")
    monkeypatch.setitem(tracing._state, "library", "openinference")
    monkeypatch.setitem(tracing._state, "variant", None)
    with tracing.worker("trueup-verifier", step="draft 1") as span:
        tracing.set_verdict(span, "fail")
    (s,) = exp.get_finished_spans()
    assert s.attributes["neatlogs.agent.output"] == s.attributes["output.value"] == "fail"
    meta = json.loads(s.attributes["metadata"])
    assert meta["trueup.step"] == "draft 1" and meta["trueup.library"] == "openinference"
    assert meta["trueup.verdict"] == "fail"


def test_mark_is_a_named_child_step_and_silent_when_off(monkeypatch):
    import contextlib
    import types

    names = []

    @contextlib.contextmanager
    def trace(name, **kw):
        names.append((name, kw.get("kind")))
        yield None

    monkeypatch.setitem(sys.modules, "neatlogs", types.SimpleNamespace(trace=trace))
    monkeypatch.setitem(tracing._state, "active", False)
    tracing.mark("lead withdrawn", rule="latest_and_main")
    assert names == []
    monkeypatch.setitem(tracing._state, "active", True)
    tracing.mark("lead withdrawn", rule="latest_and_main")
    assert names == [("lead withdrawn", "TOOL")]
