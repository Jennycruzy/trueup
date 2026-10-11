"""Read Trueup's own traces back from neatlogs, through the neatlogs MCP server.

The Public API (app.neatlogs.com/api/v1/public) answers 401 to the project's ingest key: its docs say
"Ingest credentials do not authorize Public API reads"; it needs a public API key or a service-account
token, which Trueup does not have. The MCP server (ingest.neatlogs.com/mcp, Streamable HTTP) takes the
project key as a bearer token, so Trueup reads its traces there.

Only read tools are allowed here. The key comes from NEATLOGS_API_KEY and is never printed or written.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

MCP_URL = "https://ingest.neatlogs.com/mcp"
READ_TOOLS = ("ping", "whoami", "search_traces", "get_trace_context")


class NeatlogsReadError(RuntimeError):
    pass


def _parse(r: httpx.Response) -> dict[str, Any]:
    """One JSON-RPC reply, from a plain JSON body or an SSE `data:` line."""
    if r.status_code != 200:
        raise NeatlogsReadError(f"neatlogs MCP: HTTP {r.status_code}")
    text = r.text
    if "text/event-stream" in r.headers.get("content-type", ""):
        lines = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = lines[-1] if lines else "{}"
    d = json.loads(text)
    if "error" in d:
        raise NeatlogsReadError(f"neatlogs MCP: {d['error'].get('message', d['error'])}")
    return d.get("result", {})


class Reader:
    def __init__(self, key: str | None = None, url: str = MCP_URL, http: httpx.Client | None = None) -> None:
        self.key = key or os.environ.get("NEATLOGS_API_KEY") or ""
        if not self.key:
            raise NeatlogsReadError("NEATLOGS_API_KEY is not set")
        self.url, self.http = url, http or httpx.Client(timeout=90)
        self.sid: str | None = None
        self._id = 0
        self._post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "trueup", "version": "0"}})
        self._post("notifications/initialized", {}, notify=True)

    def _post(self, method: str, params: dict[str, Any], notify: bool = False) -> dict[str, Any]:
        h = {"Authorization": f"Bearer {self.key}", "Accept": "application/json, text/event-stream",
             "Content-Type": "application/json"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            self._id += 1
            body["id"] = self._id
        r = self.http.post(self.url, headers=h, json=body)
        self.sid = r.headers.get("mcp-session-id", self.sid)
        return {} if notify else _parse(r)

    def call(self, tool: str, **args: Any) -> Any:
        if tool not in READ_TOOLS:
            raise NeatlogsReadError(f"{tool} is not a read tool")
        res = self._post("tools/call", {"name": tool, "arguments": args})
        if res.get("isError"):
            raise NeatlogsReadError(f"{tool}: {res.get('content')}")
        if "structuredContent" in res:
            return res["structuredContent"]
        texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        try:
            return json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]
        except (json.JSONDecodeError, IndexError):
            return texts


# Field projection on search_traces and get_trace_context answered "not_enabled" (NL-1923, NL-1924
# rollouts) on 2026-10-11, so both are called without `fields` and trimmed here.
def session(reader: Reader, session_id: str, clip: int = 400) -> dict[str, Any]:
    """Every trace of one Trueup run (session id = run id), trimmed: per trace its worker, step, verdict,
    tokens and latency; per model span its duration and the head of its output."""
    found = reader.call("search_traces", query=session_id, limit=100)
    ids = sorted({x["trace_id"] for x in found.get("results", []) if x.get("session_id") == session_id})
    traces = []
    for tid in ids:
        c = reader.call("get_trace_context", trace_id=tid)
        traces.append({
            "trace_id": tid, "name": c.get("name"), "created_at": c.get("created_at"),
            "status": c.get("status"), "latency_ms": c.get("latency_ms"), "llm_calls": c.get("llm_calls"),
            "prompt_tokens": c.get("prompt_tokens"), "completion_tokens": c.get("completion_tokens"),
            "spans": [{"name": s["name"], "type": s.get("type"), "status": s.get("status"),
                       "duration_ms": s.get("duration_ms"),
                       "output_head": (s.get("output_value") or "")[:clip] if s.get("type") == "llm" else None}
                      for s in c.get("spans", [])]})
    traces.sort(key=lambda t: t["created_at"] or "")
    tot = lambda k: sum(t[k] or 0 for t in traces)  # noqa: E731
    return {"session_id": session_id, "source": MCP_URL, "traces": traces,
            "totals": {"traces": len(traces), "llm_calls": tot("llm_calls"), "prompt_tokens": tot("prompt_tokens"),
                       "completion_tokens": tot("completion_tokens")}}
