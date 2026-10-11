"""Opt-in local forwarding proxy used as truth for real-provider audits.

Authentication is forwarded in memory but never written. Recordings are local
JSON Lines files and may contain prompts and responses, so callers must opt in.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

SENSITIVE_HEADERS = {"authorization", "api-key", "x-api-key", "proxy-authorization", "cookie", "set-cookie"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
               "transfer-encoding", "upgrade", "host", "content-length"}


def redact_headers(headers: Any) -> dict[str, str]:
    return {str(k): "[REDACTED]" if str(k).lower() in SENSITIVE_HEADERS else str(v)
            for k, v in headers.items()}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    upstream: str
    output: Path
    lock: threading.Lock
    client: httpx.Client

    def record(self, payload: dict[str, Any]) -> None:
        with self.lock:
            with self.output.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, *_: Any) -> None:
        pass

    def do_POST(self) -> None:
        self._forward()

    def do_GET(self) -> None:
        self._forward()

    def _forward(self) -> None:
        started = time.time()
        request_body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        url = self.server.upstream.rstrip("/") + self.path
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        chunks: list[bytes] = []
        status = 502
        response_headers: dict[str, str] = {}
        error = None
        try:
            with self.server.client.stream(self.command, url, headers=headers, content=request_body) as response:
                status = response.status_code
                response_headers = dict(response.headers)
                self.send_response(status)
                for key, value in response.headers.items():
                    if key.lower() not in HOP_HEADERS and key.lower() not in SENSITIVE_HEADERS:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in response.iter_raw():
                    chunks.append(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except Exception as exc:  # noqa: BLE001 - the failed transport is recorded as truth
            error = f"{type(exc).__name__}: {exc}"
            if not chunks:
                body = json.dumps({"error": {"message": "recording proxy upstream failure"}}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
        finally:
            self.close_connection = True
            self.server.record({
                "method": self.command,
                "path": self.path,
                "upstream": self.server.upstream,
                "request_headers": redact_headers(self.headers),
                "request_body_b64": base64.b64encode(request_body).decode(),
                "status": status,
                "response_headers": redact_headers(response_headers),
                "response_chunks_b64": [base64.b64encode(x).decode() for x in chunks],
                "error": error,
                "started_at_unix": started,
                "duration_ms": round((time.time() - started) * 1000, 3),
            })


class RecordingProxy:
    """Forward one provider origin through a local HTTP endpoint and record it."""

    def __init__(self, upstream: str, output: Path, timeout: float = 180) -> None:
        if not upstream.startswith(("https://", "http://")):
            raise ValueError("recording upstream must be an http(s) URL")
        self.upstream = upstream.rstrip("/")
        self.output = output
        self.timeout = timeout
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> RecordingProxy:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        server = _Server(("127.0.0.1", 0), _Handler)
        server.upstream = self.upstream
        server.output = self.output
        server.lock = threading.Lock()
        server.client = httpx.Client(timeout=self.timeout)
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="trueup-recording-proxy", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server.client.close()
            self._server = None

    def __enter__(self) -> RecordingProxy:
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.stop()

    @property
    def base_url(self) -> str:
        assert self._server is not None, "recording proxy not started"
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def read_recordings(path: Path) -> list[dict[str, Any]]:
    return [] if not path.exists() else [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _events(body: bytes) -> list[dict[str, Any]]:
    events = []
    for line in body.splitlines():
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            continue
        try:
            events.append(json.loads(data))
        except ValueError:
            pass
    return events


def truth_log(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize recorded OpenAI/Anthropic responses into the fake truth-log shape."""
    return [_truth_entry(record) for record in records]


def _truth_entry(record: dict[str, Any]) -> dict[str, Any]:
    path = record["path"].split("?", 1)[0]
    request = json.loads(base64.b64decode(record["request_body_b64"]) or b"{}")
    body = b"".join(base64.b64decode(x) for x in record["response_chunks_b64"])
    content_type = next((v for k, v in record["response_headers"].items() if k.lower() == "content-type"), "")
    stream = "event-stream" in content_type
    payloads = _events(body) if stream else []
    if not stream:
        try:
            payloads = [json.loads(body)]
        except ValueError:
            payloads = []
    response_id = None
    finish: list[str] = []
    usage = None
    tool_calls: list[dict[str, Any]] = []
    text: list[str] = []
    for payload in payloads:
        response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
        response_id = response.get("id") or payload.get("message", {}).get("id") or response_id
        u = response.get("usage") or payload.get("usage")
        if u:
            usage = {
                "input_tokens": u.get("input_tokens", u.get("prompt_tokens", 0)),
                "output_tokens": u.get("output_tokens", u.get("completion_tokens", 0)),
            }
        for choice in payload.get("choices", []):
            reason = choice.get("finish_reason")
            if reason is not None:
                finish.append(reason)
            msg = choice.get("message") or choice.get("delta") or {}
            if msg.get("content"):
                text.append(msg["content"])
            tool_calls.extend(msg.get("tool_calls") or [])
        if response.get("stop_reason"):
            finish.append(response["stop_reason"])
        if response.get("status"):
            finish.append(response["status"])
        for item in response.get("output", []) or []:
            if item.get("type") in {"function_call", "tool_call"}:
                tool_calls.append({"name": item.get("name"), "arguments": item.get("arguments")})
            for part in item.get("content", []) or []:
                if part.get("text"):
                    text.append(part["text"])
        for block in response.get("content", []) or []:
            if block.get("type") == "text" and block.get("text"):
                text.append(block["text"])
            if block.get("type") == "tool_use":
                tool_calls.append({"name": block.get("name"), "arguments": block.get("input")})
        if payload.get("delta", {}).get("stop_reason"):
            finish.append(payload["delta"]["stop_reason"])
        if payload.get("type") in {"response.output_text.delta", "content_block_delta"}:
            delta = payload.get("delta")
            if isinstance(delta, str):
                text.append(delta)
            elif isinstance(delta, dict) and delta.get("text"):
                text.append(delta["text"])
    status = int(record["status"])
    return {
        "api": "anthropic.messages" if path.endswith("/messages") else
               "openai.responses" if path.endswith("/responses") else "openai.chat",
        "path": path,
        "scenario": "recorded-real-provider",
        "stream": bool(request.get("stream")),
        "include_usage": bool((request.get("stream_options") or {}).get("include_usage")),
        "response_id": response_id,
        "outcome": ("http_error" if not 200 <= status < 300 else
                    "failed" if "failed" in finish else "incomplete" if "incomplete" in finish else "complete"),
        "usage": usage,
        "finish": finish,
        "tool_calls": tool_calls,
        "text": text,
        "status": status,
    }

