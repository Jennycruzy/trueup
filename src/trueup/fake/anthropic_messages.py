"""Anthropic Messages: POST /v1/messages."""

from __future__ import annotations

import json
from typing import Any

from trueup.fake.reply import Ids, Reply, json_reply, sse, stream_reply

SCENARIOS = (
    "anth-plain",
    "anth-thinking",
    "anth-tools",
    "anth-error-event",
    "anth-cut",
    "anth-529",
)
INPUT_TOKENS = 5
OUTPUT_TOKENS = 3
THINKING = "Need the weather."
TOOL_INPUT = {"city": "Lagos"}


def _content(scenario: str, ids: Ids) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if scenario in ("anth-thinking", "anth-tools"):
        blocks.append({"type": "thinking", "thinking": THINKING, "signature": "fake-sig"})
    blocks.append({"type": "text", "text": "hello"})
    if scenario == "anth-tools":
        blocks.append({"type": "tool_use", "id": ids.new("toolu_"), "name": "get_weather", "input": TOOL_INPUT})
    return blocks


def _facts(mid: str, content: list[dict[str, Any]], stop: str) -> dict[str, Any]:
    return {
        "response_id": mid,
        "usage": {"input_tokens": INPUT_TOKENS, "output_tokens": OUTPUT_TOKENS, "total_tokens": INPUT_TOKENS + OUTPUT_TOKENS},
        "finish": [stop],
        "tool_calls": [
            {"id": b["id"], "name": b["name"], "arguments": json.dumps(b["input"], separators=(",", ":"))}
            for b in content
            if b["type"] == "tool_use"
        ],
        "text": ["".join(b["text"] for b in content if b["type"] == "text")],
    }


def handle(scenario: str, req: dict[str, Any], ids: Ids) -> Reply:
    if scenario == "anth-529":
        return json_reply(
            529,
            {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
            outcome="http_error",
        )
    mid = ids.new("msg_")
    model = req.get("model", "")
    content = _content(scenario, ids)
    stop = "tool_use" if scenario == "anth-tools" else "end_turn"
    if not req.get("stream"):
        body = {
            "id": mid,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": INPUT_TOKENS, "output_tokens": OUTPUT_TOKENS},
        }
        if scenario == "anth-cut":
            raw = json.dumps(body).encode()
            return Reply(200, raw[: len(raw) // 2], cut=True, response_id=mid, outcome="cut")
        if scenario == "anth-error-event":
            return json_reply(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "anth-error-event needs stream=true"}}, outcome="http_error")
        return json_reply(200, body, **_facts(mid, content, stop))

    def ev(kind: str, **data: Any) -> bytes:
        return sse({"type": kind, **data}, event=kind)

    parts = [
        ev("message_start", message={
            "id": mid, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": INPUT_TOKENS, "output_tokens": 1},
        })
    ]
    for i, block in enumerate(content):
        if block["type"] == "thinking":
            parts += [
                ev("content_block_start", index=i, content_block={"type": "thinking", "thinking": "", "signature": ""}),
                ev("content_block_delta", index=i, delta={"type": "thinking_delta", "thinking": block["thinking"]}),
                ev("content_block_delta", index=i, delta={"type": "signature_delta", "signature": block["signature"]}),
            ]
        elif block["type"] == "text":
            parts += [
                ev("content_block_start", index=i, content_block={"type": "text", "text": ""}),
                ev("content_block_delta", index=i, delta={"type": "text_delta", "text": "hel"}),
            ]
            if scenario == "anth-error-event":
                parts.append(ev("error", error={"type": "overloaded_error", "message": "Overloaded"}))
                return stream_reply(parts, response_id=mid, outcome="error_event", text=["hel"])
            if scenario == "anth-cut":
                return stream_reply(parts, cut=True, response_id=mid, outcome="cut", text=["hel"])
            parts.append(ev("content_block_delta", index=i, delta={"type": "text_delta", "text": "lo"}))
        else:
            parts += [
                ev("content_block_start", index=i, content_block={"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}),
                ev("content_block_delta", index=i, delta={"type": "input_json_delta", "partial_json": '{"city": '}),
                ev("content_block_delta", index=i, delta={"type": "input_json_delta", "partial_json": '"Lagos"}'}),
            ]
        parts.append(ev("content_block_stop", index=i))
    parts += [
        ev("message_delta", delta={"stop_reason": stop, "stop_sequence": None}, usage={"output_tokens": OUTPUT_TOKENS}),
        ev("message_stop"),
    ]
    return stream_reply(parts, **_facts(mid, content, stop))
