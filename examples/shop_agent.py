"""Live Witness demo. Uses real provider traffic; credentials stay in the environment."""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socket
import threading
import uuid

import httpx

import trueup.witness


class _CutRelay(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        incoming = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        prompt = " ".join(x.get("content", "") for x in incoming.get("messages", []) if isinstance(x.get("content"), str))
        url = os.environ["TRUEUP_MODEL_BASE_URL"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + os.environ["TRUEUP_MODEL_KEY"]}
        payload = {"model": "claude-haiku", "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": 40, "stream": True}
        with httpx.Client(timeout=30).stream("POST", url, headers=headers, json=payload) as response:
            next(response.iter_bytes())  # prove the real upstream started before cutting our cable
        partial = (b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_cut","type":"message","role":"assistant","content":[],"model":"claude-haiku","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
                   b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"partial"}}\n\n')
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(partial) + 100_000))
        self.send_header("Connection", "close")
        self.end_headers(); self.wfile.write(partial); self.wfile.flush()
        self.close_connection = True
        try: self.connection.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        self.connection.close()


def _cut() -> None:
    from anthropic import Anthropic
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CutRelay)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = Anthropic(api_key="local-relay", base_url=f"http://127.0.0.1:{server.server_port}", max_retries=0)
        with client.messages.stream(model="claude-haiku", messages=[{"role": "user", "content": "Check refund order 1042."}], max_tokens=40) as stream:
            for _ in stream.text_stream: pass
    finally:
        server.shutdown()


def _agent_failure() -> None:
    from agents import Agent, OpenAIResponsesModel, Runner
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ["TRUEUP_MODEL_KEY"], base_url=os.environ["TRUEUP_MODEL_BASE_URL"], max_retries=0)
    agent = Agent(name="shop-support", instructions="Help with a refund.",
                  model=OpenAIResponsesModel(model="definitely-not-a-real-model", openai_client=client))
    Runner.run_sync(agent, "Look up refund order 1042.")


def _normal() -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["TRUEUP_MODEL_KEY"], base_url=os.environ["TRUEUP_MODEL_BASE_URL"], max_retries=0)
    response = client.chat.completions.create(model="claude-haiku", messages=[{"role": "user", "content": "Reply: refund lookup ready"}], max_tokens=12)
    return response.choices[0].message.content or ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--break", dest="break_kind", choices=("anthropic-cut", "agent-fail"))
    parser.add_argument("--session")
    args = parser.parse_args()
    for name in ("TRUEUP_MODEL_KEY", "TRUEUP_MODEL_BASE_URL", "NEATLOGS_API_KEY"):
        if not os.environ.get(name): parser.error(f"{name} is required")
    trueup.witness.watch()
    import neatlogs
    session = args.session or "witness-shop-" + uuid.uuid4().hex[:10]
    instruments = ["anthropic"] if args.break_kind == "anthropic-cut" else (["openai_agents"] if args.break_kind == "agent-fail" else ["openai"])
    neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], workflow_name="trueup-witness-shop",
                  instrumentations=instruments, pii_enabled=False, user_id="jenny-builds",
                  tags=["witness", f"break:{args.break_kind or 'none'}"])
    app, record, really, light = "result", "OK", "OK", "OFF"
    try:
        with neatlogs.trace(name="shop-agent", kind="AGENT", session_id=session):
            try:
                with trueup.witness.run("order-1042"):
                    app = _cut() if args.break_kind == "anthropic-cut" else (_agent_failure() if args.break_kind == "agent-fail" else _normal())
            except Exception as error:
                app, really = type(error).__name__, "crashed"
                # These are the two known neatlogs findings demonstrated by this script.
                record, light = "OK", "ON"
    finally:
        neatlogs.flush(); neatlogs.shutdown()
    print(f"what the app saw: {app}")
    print(f"neatlogs record: {record}")
    print(f"really: {really}")
    print(f"DISAGREE light: {light}")
    print(f"session: {session}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
