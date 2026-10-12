"""Safety rules of the live demo server (live/server.py), with no real model call and no real subprocess."""
from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_PY = Path(__file__).resolve().parent.parent / "live" / "server.py"


def _load():
    spec = importlib.util.spec_from_file_location("trueup_live_server", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = _load()


class FakeThread:
    started: list[tuple] = []

    def __init__(self, target=None, args=(), daemon=None):
        self.args = args

    def start(self):
        FakeThread.started.append(self.args)


def _no_subprocess(*args, **kwargs):
    raise AssertionError("a real subprocess was started")


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "STATE_FILE", tmp_path / "state.json")
    # Replace only the server module's names: the HTTP server itself still needs the real threading module.
    monkeypatch.setattr(live, "threading", SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(live, "subprocess", SimpleNamespace(
        run=_no_subprocess, TimeoutExpired=subprocess.TimeoutExpired, CompletedProcess=subprocess.CompletedProcess))
    monkeypatch.setattr(live, "_jobs", {})
    monkeypatch.setattr(live, "_last_by_ip", {})
    FakeThread.started = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), live.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def _run(port, brk="normal", mode="released", ip="1.2.3.4"):
    body = json.dumps({"break": brk, "mode": mode})
    return _request(port, "POST", "/api/run", body, {"Content-Type": "application/json", "X-Real-IP": ip})


@pytest.mark.parametrize("brk", ["normal", "cut", "agent"])
@pytest.mark.parametrize("mode", ["released", "fixed"])
def test_the_three_breaks_and_two_modes_are_accepted(server, brk, mode):
    resp, data = _run(server, brk, mode, ip=f"{brk}-{mode}")
    assert resp.status == 202
    assert FakeThread.started == [(json.loads(data)["id"], brk, mode)]


@pytest.mark.parametrize("body", [
    {"break": "drop table", "mode": "released"},
    {"break": "normal", "mode": "../../bin/sh"},
    {"break": "normal"},
    {"mode": "fixed"},
    {"break": ["normal"], "mode": "fixed"},
    {},
])
def test_anything_else_is_refused(server, body):
    resp, _ = _request(server, "POST", "/api/run", json.dumps(body))
    assert resp.status == 400
    assert FakeThread.started == []


@pytest.mark.parametrize("body", ["not json", '["normal", "released"]', "42", "null"])
def test_bad_json_is_refused(server, body):
    resp, _ = _request(server, "POST", "/api/run", body)
    assert resp.status == 400


def test_other_post_paths_are_not_found(server):
    resp, _ = _request(server, "POST", "/api/other", "{}")
    assert resp.status == 404


def test_body_is_read_only_up_to_the_cap(server):
    start = json.dumps({"break": "normal", "mode": "released"})
    # Valid JSON fills the first 200 bytes; anything past the cap would break the parse if it were read.
    body = start + " " * (200 - len(start)) + "GARBAGE" * 100
    resp, _ = _request(server, "POST", "/api/run", body)
    assert resp.status == 202


def test_negative_content_length_does_not_read_without_a_limit(server):
    with socket.create_connection(("127.0.0.1", server), timeout=5) as s:
        s.sendall(b"POST /api/run HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n"
                  b'{"break": "normal", "mode": "released"}')
        # The connection stays open: a read without a limit would wait here until the timeout.
        reply = s.recv(4096)
    assert reply.startswith(b"HTTP/1.0 400")


def test_same_visitor_inside_cool_down_gets_429(server):
    assert _run(server, ip="5.5.5.5")[0].status == 202
    assert _run(server, ip="5.5.5.5")[0].status == 429
    assert _run(server, ip="6.6.6.6")[0].status == 202
    assert len(FakeThread.started) == 2


def test_cool_down_ends(server, monkeypatch):
    assert _run(server, ip="5.5.5.5")[0].status == 202
    live._last_by_ip["5.5.5.5"] -= live.COOLDOWN_S + 1
    assert _run(server, ip="5.5.5.5")[0].status == 202


def test_run_in_progress_gets_429(server):
    with live._run_lock:
        resp, data = _run(server)
        assert resp.status == 429
        assert "Someone else" in json.loads(data)["error"]
        stats = json.loads(_request(server, "GET", "/api/stats")[1])
        assert stats["busy"] is True
    assert FakeThread.started == []
    assert _run(server, ip="7.7.7.7")[0].status == 202


def test_daily_cap_blocks_runs_and_count_stops_at_the_cap(server, monkeypatch):
    monkeypatch.setattr(live, "DAILY_CAP", 2)
    assert live._count("released", "normal", False) is True
    assert live._count("released", "normal", False) is True
    assert live._count("released", "normal", False) is False
    assert live._stats()["today"] == 2
    resp, data = _run(server)
    assert resp.status == 429
    assert "used up" in json.loads(data)["error"]
    assert FakeThread.started == []


def test_state_counts_runs_and_light_per_mode_and_break(server):
    live._count("released", "cut", True)
    live._count("released", "cut", False)
    live._count("fixed", "cut", False)
    live._count("released", "agent", True)
    state = json.loads(live.STATE_FILE.read_text())
    assert state["totals"] == {
        "released:cut": {"runs": 2, "lit": 1},
        "fixed:cut": {"runs": 1, "lit": 0},
        "released:agent": {"runs": 1, "lit": 1},
    }
    assert state["days"][live._today()]["runs"] == 4


def test_a_new_day_starts_at_zero(server, monkeypatch):
    monkeypatch.setattr(live, "DAILY_CAP", 1)
    monkeypatch.setattr(live, "_today", lambda: "2026-10-12")
    assert live._count("released", "normal", False) is True
    assert live._count("released", "normal", False) is False
    monkeypatch.setattr(live, "_today", lambda: "2026-10-13")
    assert live._stats()["today"] == 0
    assert live._count("released", "normal", False) is True
    state = json.loads(live.STATE_FILE.read_text())
    assert state["days"] == {"2026-10-12": {"runs": 1}, "2026-10-13": {"runs": 1}}
    assert state["totals"]["released:normal"]["runs"] == 2


def test_run_counts_the_light_without_a_real_call(server, monkeypatch):
    def fake_run(cmd, **kwargs):
        Path(cmd[cmd.index("--json-out") + 1]).write_text(json.dumps({"disagreements": [{"field": "call_status"}]}))
        assert cmd[cmd.index("--break") + 1] == "anthropic-cut"
        return live.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(live.subprocess, "run", fake_run)
    monkeypatch.setattr(live, "_read_record", lambda *a: None)
    live._jobs["j1"] = {"id": "j1", "stage": "queued", "created": 0}
    live._run("j1", "cut", "released")
    assert live._jobs["j1"]["stage"] == "done"
    assert live._stats()["totals"] == {"released:cut": {"runs": 1, "lit": 1}}


def test_job_never_returns_the_visitor_ip(server):
    resp, data = _run(server, ip="203.0.113.9")
    job_id = json.loads(data)["id"]
    live._jobs[job_id]["ip"] = "203.0.113.9"  # even if a later change stores it
    resp, data = _request(server, "GET", f"/api/job/{job_id}")
    assert resp.status == 200
    assert "ip" not in json.loads(data)
    assert b"203.0.113.9" not in data
    assert b"127.0.0.1" not in data


def test_unknown_job_is_not_found(server):
    assert _request(server, "GET", "/api/job/nope")[0].status == 404


@pytest.fixture
def images(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs" / "x").mkdir(parents=True)
    (repo / "docs" / "x" / "1-shot.png").write_bytes(b"\x89PNG ok")
    (repo / "docs" / "secret.png").write_bytes(b"secret")
    (repo / "secret.png").write_bytes(b"secret")
    monkeypatch.setattr(live, "REPO", repo)


def test_download_sends_attachment(server, images):
    resp, data = _request(server, "GET", "/download/1-shot.png")
    assert resp.status == 200
    assert resp.getheader("Content-Disposition") == 'attachment; filename="1-shot.png"'
    assert data == b"\x89PNG ok"
    resp, _ = _request(server, "GET", "/x/1-shot.png")
    assert resp.status == 200
    assert resp.getheader("Content-Disposition") is None


@pytest.mark.parametrize("path", [
    "/download/../secret.png",
    "/download/../../secret.png",
    "/download/..%2fsecret.png",
    "/download/..%2F..%2Fsecret.png",
    "/download/%2e%2e/secret.png",
    "/x/../secret.png",
    "/download/../../../../etc/passwd.png",
    "/download/1-shot.png/../../secret.png",
])
def test_paths_outside_docs_x_are_not_served(server, images, path):
    resp, data = _request(server, "GET", path)
    assert resp.status == 404
    assert b"secret" not in data


@pytest.fixture
def site(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    for name in ("index", "demo", "how-it-works", "fixes", "built-with"):
        (static / f"{name}.html").write_text(f"<!doctype html><title>{name}</title>")
    (static / "site.css").write_text("body{}")
    (static / "site.js").write_text("// js")
    (static / "notes.txt").write_text("secret")
    (tmp_path / "secret.html").write_text("secret")
    monkeypatch.setattr(live, "STATIC", static)
    return static


@pytest.mark.parametrize("path,name", [
    ("/", "index"), ("/index.html", "index"), ("/demo", "demo"), ("/demo.html", "demo"),
    ("/how-it-works", "how-it-works"), ("/how-it-works.html", "how-it-works"), ("/fixes", "fixes"),
    ("/fixes.html", "fixes"), ("/built-with", "built-with"), ("/built-with.html", "built-with"),
    ("/demo?from=nav", "demo"),
])
def test_site_pages_are_served(server, site, path, name):
    resp, data = _request(server, "GET", path)
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/html; charset=utf-8"
    assert f"<title>{name}</title>".encode() in data


@pytest.mark.parametrize("path,ctype", [("/site.css", "text/css"), ("/site.js", "text/javascript")])
def test_site_assets_are_served(server, site, path, ctype):
    resp, _ = _request(server, "GET", path)
    assert resp.status == 200
    assert resp.getheader("Content-Type").startswith(ctype)


def test_a_missing_page_is_not_found(server, site):
    (site / "fixes.html").unlink()
    assert _request(server, "GET", "/fixes")[0].status == 404


@pytest.mark.parametrize("path", [
    "/nope", "/notes.txt", "/static/index.html", "/demo/", "/Demo", "/../secret.html", "/..%2fsecret.html",
    "/%2e%2e/secret.html", "/demo/../../secret.html", "/./demo", "/site.css/../secret.html",
    "/server.py", "/../live/server.py", "/x/../../live/server.py", "/fixes.html/..",
])
def test_unknown_and_escaping_paths_are_not_found(server, site, path):
    resp, data = _request(server, "GET", path)
    assert resp.status == 404
    assert b"secret" not in data


def test_api_routes_still_answer_beside_the_site(server, site):
    assert _request(server, "GET", "/api/stats")[0].status == 200
    assert _request(server, "GET", "/api/job/nope")[0].status == 404
    assert _run(server, ip="8.8.8.8")[0].status == 202
