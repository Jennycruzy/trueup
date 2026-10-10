"""Local HTTP fake provider. Runs in a thread on a random free port."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from trueup.fake import anthropic_messages, openai_chat, openai_responses
from trueup.fake.reply import Ids, Reply, json_reply

ROUTES: dict[str, tuple[str, Callable[[str, dict[str, Any], Ids], Reply]]] = {
    "/v1/chat/completions": ("openai.chat", openai_chat.handle),
    "/v1/responses": ("openai.responses", openai_responses.handle),
    "/v1/messages": ("anthropic.messages", anthropic_messages.handle),
}
SCENARIOS = openai_chat.SCENARIOS + openai_responses.SCENARIOS + anthropic_messages.SCENARIOS


class TruthLog:
    """Every request the fake got and what it sent back. Thread-safe."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def add(self, entry: dict[str, Any]) -> None:
        with self._lock:
            entry["seq"] = len(self._entries) + 1
            self._entries.append(entry)

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(self._entries))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def summary(self) -> dict[str, Any]:
        entries = self.entries()
        return {
            "calls": len(entries),
            "tokens_per_call": [e["usage"] for e in entries],
            "response_ids": [e["response_id"] for e in entries],
        }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = self.path.split("?", 1)[0]
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            req = {}
        api, handler = ROUTES.get(path, ("unknown", None))
        scenario = str(req.get("model", ""))
        if handler is None:
            reply = json_reply(404, {"error": {"message": f"no route {path}", "type": "not_found"}}, outcome="http_error")
        else:
            reply = handler(scenario, req, self.server.ids)
        self.server.log.add({
            "api": api,
            "path": path,
            "scenario": scenario,
            "stream": bool(req.get("stream")),
            "include_usage": bool((req.get("stream_options") or {}).get("include_usage")),
            "n": req.get("n"),
            **reply.facts(),
        })
        self._send(reply)

    def _send(self, reply: Reply) -> None:
        self.send_response(reply.status)
        self.send_header("Content-Type", reply.content_type)
        for k, v in reply.headers.items():
            self.send_header(k, v)
        if reply.cut:
            # Promise more bytes than we send, then drop the connection.
            self.send_header("Content-Length", str(len(reply.body) + 512))
            self.end_headers()
            self.wfile.write(reply.body)
            self.wfile.flush()
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.close_connection = True
            return
        self.send_header("Content-Length", str(len(reply.body)))
        self.end_headers()
        self.wfile.write(reply.body)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    log: TruthLog
    ids: Ids


class FakeProvider:
    """Use as a context manager, or call start() and stop()."""

    def __init__(self) -> None:
        self.log = TruthLog()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> FakeProvider:
        server = _Server(("127.0.0.1", 0), _Handler)
        server.log = self.log
        server.ids = Ids()
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, name="trueup-fake", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> FakeProvider:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    @property
    def port(self) -> int:
        assert self._server is not None, "fake not started"
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        """Anthropic base_url (the SDK adds /v1)."""
        return f"http://127.0.0.1:{self.port}"

    @property
    def openai_base_url(self) -> str:
        return f"{self.base_url}/v1"
