"""Crash it yourself: the live Trueup Witness demo server.

A visitor presses one of three buttons. The server runs examples/shop_agent.py once, for real: a real Claude
call through the event's model key, traced into neatlogs, with Witness watching. Then it reads the record back
from neatlogs and returns both, so the page can show what really happened next to what neatlogs recorded.

Safety: only the three fixed breaks exist (no visitor text reaches the model); one run at a time; a short
cool-down per visitor; a daily cap. Keys come from the environment and never reach the page.

It also serves the product site: / /demo /how-it-works /fixes /built-with, site.css and site.js
(live/build_fixes.py writes fixes.html).

Run: python live/server.py  (reads TRUEUP_MODEL_KEY, TRUEUP_MODEL_BASE_URL, NEATLOGS_API_KEY,
LIVE_PY_RELEASED, LIVE_PY_FIXED, optional LIVE_PORT, LIVE_DAILY_CAP, LIVE_STATE).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from trueup.neatlogs_read import Reader  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
# Only these names are ever served from STATIC: a fixed list, so no path can reach another file.
PAGES = {"/": "index.html"}
for _page in ("index", "demo", "how-it-works", "fixes", "built-with"):
    PAGES.setdefault(f"/{_page}", f"{_page}.html")
    PAGES[f"/{_page}.html"] = f"{_page}.html"
ASSETS = {"/site.css": ("site.css", "text/css; charset=utf-8"),
          "/site.js": ("site.js", "text/javascript; charset=utf-8")}
BREAKS = {"normal": None, "cut": "anthropic-cut", "agent": "agent-fail"}
PYTHONS = {"released": os.environ.get("LIVE_PY_RELEASED", str(REPO / ".venv" / "bin" / "python")),
           "fixed": os.environ.get("LIVE_PY_FIXED", str(REPO / ".trueup" / "live" / "venv-fixed" / "bin" / "python"))}
DAILY_CAP = int(os.environ.get("LIVE_DAILY_CAP", "300"))
COOLDOWN_S = 8
STATE_FILE = Path(os.environ.get("LIVE_STATE", str(REPO / ".trueup" / "live" / "state.json")))

_run_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_last_by_ip: dict[str, float] = {}
_state_lock = threading.Lock()


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _stats() -> dict:
    with _state_lock:
        s = _load_state()
        day = s.get("days", {}).get(_today(), {"runs": 0})
        total = s.get("totals", {})
    return {"today": day.get("runs", 0), "cap": DAILY_CAP, "totals": total}


def _count(mode: str, brk: str, lit: bool) -> bool:
    """Count one run; False if today's cap is reached."""
    with _state_lock:
        s = _load_state()
        days = s.setdefault("days", {})
        day = days.setdefault(_today(), {"runs": 0})
        if day["runs"] >= DAILY_CAP:
            return False
        day["runs"] += 1
        key = f"{mode}:{brk}"
        t = s.setdefault("totals", {}).setdefault(key, {"runs": 0, "lit": 0})
        t["runs"] += 1
        t["lit"] += int(lit)
        _save_state(s)
        return True


def _read_record(session: str, started: float, job: dict) -> dict | None:
    """Poll neatlogs until the trace for this session is stored, then return its steps."""
    reader = Reader()
    since = dt.datetime.fromtimestamp(started - 30, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    deadline = time.time() + 75
    tries = 0
    while time.time() < deadline:
        tries += 1
        job["read_tries"] = tries
        for query in ("shop-agent", "TRACE DISAGREE", "claude-haiku", "Agent workflow"):
            try:
                res = reader.call("search_traces", query=query, limit=50, date_from=since)
            except Exception:
                continue
            for t in res.get("results", []):
                if t.get("session_id") == session:
                    ctx = reader.call("get_trace_context", trace_id=t["trace_id"])
                    steps = [{"name": s.get("name"), "status": s.get("status"), "type": s.get("type"),
                              "id": s.get("span_id"), "parent": s.get("parent_span_id")}
                             for s in ctx.get("spans", [])]
                    return {"trace_id": t["trace_id"], "status": t.get("status"),
                            "url": "https://app.neatlogs.com/traces/" + t["trace_id"], "steps": steps}
        time.sleep(4)
    return None


def _run(job_id: str, brk: str, mode: str) -> None:
    job = _jobs[job_id]
    try:
        with _run_lock:
            job["stage"] = "calling"
            started = time.time()
            session = f"live-{mode}-{brk}-{job_id[:8]}"
            out = Path(tempfile.mkstemp(prefix="trueup-live-", suffix=".json")[1])
            cmd = [PYTHONS[mode], str(REPO / "examples" / "shop_agent.py"), "--session", session,
                   "--json-out", str(out)]
            if BREAKS[brk]:
                cmd += ["--break", BREAKS[brk]]
            p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=90)
            try:
                result = json.loads(out.read_text())
            except Exception:
                result = None
            finally:
                out.unlink(missing_ok=True)
            if result is None:
                job.update(stage="failed", error="The run did not finish. Please try again.",
                           detail=(p.stderr or "")[-300:].splitlines()[-1:] if p.returncode else [])
                return
            job["elapsed_run_s"] = round(time.time() - started, 1)
            job["result"] = result
            lit = bool(result.get("disagreements"))
            _count(mode, brk, lit)
        job["stage"] = "reading"
        job["record"] = _read_record(session, started, job)
        job["stage"] = "done"
    except subprocess.TimeoutExpired:
        job.update(stage="failed", error="The AI call took too long. Please try again.")
    except Exception as error:  # never leak details to the page
        job.update(stage="failed", error="Something went wrong on our side.")
        print("job error:", type(error).__name__, error, file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = "trueup-live"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _ip(self) -> str:
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path, ctype: str, download: bool = False) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in PAGES or path in ASSETS:
            name, ctype = ASSETS[path] if path in ASSETS else (PAGES[path], "text/html; charset=utf-8")
            f = STATIC / name
            if f.is_file():
                return self._file(f, ctype)
            return self._json(404, {"error": "not found"})
        if path == "/api/stats":
            return self._json(200, dict(_stats(), busy=_run_lock.locked()))
        if path.startswith("/api/job/"):
            job = _jobs.get(path.rsplit("/", 1)[-1])
            if not job:
                return self._json(404, {"error": "unknown run"})
            return self._json(200, {k: v for k, v in job.items() if k != "ip"})
        if path == "/submission-kit":
            f = REPO / ".trueup" / "live" / "submission.html"
            if f.is_file():
                return self._file(f, "text/html; charset=utf-8")
        if path == "/download/trueup-demo.mp4":
            f = REPO / ".trueup" / "live" / "trueup-demo.mp4"
            if f.is_file():
                return self._file(f, "video/mp4", download=True)
        if path == "/download/submission.txt":
            f = REPO / ".trueup" / "live" / "submission.txt"
            if f.is_file():
                return self._file(f, "text/plain; charset=utf-8", download=True)
        if (path.startswith("/x/") or path.startswith("/download/")) and path.endswith(".png"):
            f = REPO / "docs" / "x" / Path(path).name
            if f.is_file():
                return self._file(f, "image/png", download=path.startswith("/download/"))
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/run":
            return self._json(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(max(0, min(int(self.headers.get("Content-Length", "0")), 200))) or b"{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        brk, mode = str(body.get("break")), str(body.get("mode"))
        if brk not in BREAKS or mode not in PYTHONS:
            return self._json(400, {"error": "Pick one of the three buttons."})
        ip = self._ip()
        now = time.time()
        if now - _last_by_ip.get(ip, 0) < COOLDOWN_S:
            return self._json(429, {"error": "One moment: give the last run a few seconds."})
        if _run_lock.locked():
            return self._json(429, {"error": "Someone else is crashing the bot right now. Try again in a few seconds."})
        if _stats()["today"] >= DAILY_CAP:
            return self._json(429, {"error": "Today's live runs are used up. Come back tomorrow."})
        _last_by_ip[ip] = now
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {"id": job_id, "break": brk, "mode": mode, "stage": "queued", "created": now}
        for old in [k for k, v in _jobs.items() if now - v["created"] > 3600]:
            _jobs.pop(old, None)
        threading.Thread(target=_run, args=(job_id, brk, mode), daemon=True).start()
        self._json(202, {"id": job_id})


def main() -> None:
    for name in ("TRUEUP_MODEL_KEY", "TRUEUP_MODEL_BASE_URL", "NEATLOGS_API_KEY"):
        if not os.environ.get(name):
            raise SystemExit(f"{name} is required")
    port = int(os.environ.get("LIVE_PORT", "8791"))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
