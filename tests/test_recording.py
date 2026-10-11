import base64
import json
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from trueup.recording import RecordingProxy, truth_log
from trueup.runner import RAN
from trueup.runner.run import run_record_audit


@pytest.fixture
def upstream():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.update(auth=self.headers.get("Authorization"), body=body, path=self.path)
            payload = b'data: {"one":1}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[:12])
            self.wfile.flush()
            self.wfile.write(payload[12:])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()
    server.server_close()


def test_proxy_forwards_stream_and_redacts_credentials(tmp_path, upstream):
    origin, seen = upstream
    output = tmp_path / "recordings.jsonl"
    with RecordingProxy(origin, output) as proxy:
        response = httpx.post(proxy.base_url + "/v1/responses?x=1", headers={"Authorization": "Bearer secret"},
                              content=b'{"model":"real"}')
    assert response.status_code == 200
    assert response.content.endswith(b"[DONE]\n\n")
    assert seen == {"auth": "Bearer secret", "body": b'{"model":"real"}', "path": "/v1/responses?x=1"}
    record = json.loads(output.read_text())
    assert record["request_headers"]["Authorization"] == "[REDACTED]"
    assert "secret" not in output.read_text()
    assert base64.b64decode(record["request_body_b64"]) == b'{"model":"real"}'
    assert b"".join(base64.b64decode(x) for x in record["response_chunks_b64"]) == response.content


def test_proxy_rejects_non_http_upstream(tmp_path):
    with pytest.raises(ValueError, match="http"):
        RecordingProxy("api.example.com", tmp_path / "recordings.jsonl")


def test_truth_log_normalizes_openai_json():
    request = base64.b64encode(b'{"model":"x"}').decode()
    response = base64.b64encode(json.dumps({
        "id": "chat-1", "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }).encode()).decode()
    records = [{"path": "/v1/chat/completions", "request_body_b64": request,
                "response_chunks_b64": [response], "status": 200,
                "response_headers": {"Content-Type": "application/json"}}]
    entry = truth_log(records)[0]
    assert entry["response_id"] == "chat-1"
    assert entry["usage"] == {"input_tokens": 3, "output_tokens": 2}
    assert entry["finish"] == ["stop"] and entry["text"] == ["hello"]


def test_truth_log_normalizes_responses_and_anthropic():
    request = base64.b64encode(b'{"model":"x"}').decode()
    bodies = [
        {"id": "resp-1", "status": "completed", "usage": {"input_tokens": 4, "output_tokens": 1},
         "output": [{"type": "message", "content": [{"type": "output_text", "text": "yes"}]}]},
        {"id": "msg-1", "stop_reason": "tool_use", "usage": {"input_tokens": 5, "output_tokens": 2},
         "content": [{"type": "tool_use", "name": "weather", "input": {"city": "Lagos"}}]},
    ]
    paths = ["/v1/responses", "/v1/messages"]
    records = [{"path": path, "request_body_b64": request,
                "response_chunks_b64": [base64.b64encode(json.dumps(body).encode()).decode()], "status": 200,
                "response_headers": {"Content-Type": "application/json"}}
               for path, body in zip(paths, bodies)]
    responses, anthropic = truth_log(records)
    assert responses["text"] == ["yes"] and responses["finish"] == ["completed"]
    assert anthropic["tool_calls"] == [{"name": "weather", "arguments": {"city": "Lagos"}}]
    assert anthropic["finish"] == ["tool_use"]


def test_record_audit_child_uses_proxy_and_real_key_without_persisting_it(tmp_path, monkeypatch):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen["auth"] = self.headers.get("Authorization")
            body = json.dumps({"id": "chat-real", "object": "chat.completion", "created": 1, "model": "x",
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": "recorded"}}],
                               "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = tmp_path / "agent.py"
    script.write_text("from openai import OpenAI\ndef main(): return OpenAI().chat.completions.create(model='x', messages=[{'role':'user','content':'hi'}]).choices[0].message.content\n")
    recording = tmp_path / "recording.jsonl"
    monkeypatch.setenv("OPENAI_API_KEY", "real-key-must-not-be-stored")
    try:
        with RecordingProxy(f"http://127.0.0.1:{server.server_address[1]}", recording) as proxy:
            result = run_record_audit(Path(sys.executable), "neatlogs", script, "openai", proxy.base_url, recording)
    finally:
        server.shutdown()
        server.server_close()
    assert result["status"] == RAN
    assert result["observation"]["truth"]["calls"] == 1
    assert result["observation"]["truth"]["tokens"] == [{"input": 3, "output": 1}]
    assert seen["auth"] == "Bearer real-key-must-not-be-stored"
    assert "real-key-must-not-be-stored" not in recording.read_text()

