"""OpenAI Responses: POST /v1/responses."""

from __future__ import annotations

import copy
import json
from typing import Any

from trueup.fake.reply import Ids, Reply, json_reply, sse, stream_reply

SCENARIOS = (
    "resp-plain",
    "resp-tool",
    "resp-reasoning",
    "resp-failed",
    "resp-incomplete",
    "resp-error-event",
    "resp-cut",
)
INPUT_TOKENS = 11
OUTPUT_TOKENS = 7
REASONING_TOKENS = 4
SUMMARY = "Think about the weather."


def _usage(reasoning: int = 0) -> dict[str, Any]:
    return {
        "input_tokens": INPUT_TOKENS,
        "output_tokens": OUTPUT_TOKENS,
        "total_tokens": INPUT_TOKENS + OUTPUT_TOKENS,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": reasoning},
    }


def _message(ids: Ids, text: str, status: str = "completed") -> dict[str, Any]:
    return {
        "type": "message",
        "id": ids.new("msg_"),
        "role": "assistant",
        "status": status,
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _body(scenario: str, model: str, ids: Ids) -> dict[str, Any]:
    reasoning = 0
    status = "completed"
    error = None
    incomplete = None
    if scenario == "resp-tool":
        output = [
            {
                "type": "function_call",
                "id": ids.new("fc_"),
                "call_id": ids.new("call_"),
                "name": "get_weather",
                "arguments": '{"city":"Lagos"}',
                "status": "completed",
            }
        ]
    elif scenario == "resp-reasoning":
        reasoning = REASONING_TOKENS
        output = [
            {"type": "reasoning", "id": ids.new("rs_"), "summary": [{"type": "summary_text", "text": SUMMARY}]},
            _message(ids, "hello"),
        ]
    elif scenario == "resp-failed":
        status = "failed"
        error = {"code": "server_error", "message": "fake response failed"}
        output = []
    elif scenario == "resp-incomplete":
        status = "incomplete"
        incomplete = {"reason": "max_output_tokens"}
        output = [_message(ids, "The answer is cut", status="incomplete")]
    else:
        output = [_message(ids, "hello")]
    return {
        "id": ids.new("resp_"),
        "object": "response",
        "created_at": 0,
        "status": status,
        "error": error,
        "incomplete_details": incomplete,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": None if status == "failed" else _usage(reasoning),
    }


def _facts(body: dict[str, Any]) -> dict[str, Any]:
    usage = body["usage"]
    texts, tools = [], []
    for item in body["output"]:
        if item["type"] == "message":
            texts.append("".join(c["text"] for c in item["content"]))
        elif item["type"] == "function_call":
            tools.append({"id": item["call_id"], "name": item["name"], "arguments": item["arguments"]})
    return {
        "response_id": body["id"],
        "outcome": body["status"] if body["status"] != "completed" else "complete",
        "usage": None
        if usage is None
        else {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "reasoning_tokens": usage["output_tokens_details"]["reasoning_tokens"],
        },
        "finish": [body["status"]],
        "tool_calls": tools,
        "text": texts,
    }


def handle(scenario: str, req: dict[str, Any], ids: Ids) -> Reply:
    body = _body(scenario, req.get("model", ""), ids)
    if not req.get("stream"):
        if scenario == "resp-cut":
            raw = json.dumps(body).encode()
            return Reply(200, raw[: len(raw) // 2], cut=True, response_id=body["id"], outcome="cut")
        if scenario == "resp-error-event":
            return json_reply(400, {"error": {"message": "resp-error-event needs stream=true", "type": "invalid_request_error"}}, outcome="http_error")
        return json_reply(200, body, **_facts(body))
    return _stream(scenario, body)


def _stream(scenario: str, body: dict[str, Any]) -> Reply:
    seq = 0
    parts: list[bytes] = []

    def ev(kind: str, **data: Any) -> None:
        nonlocal seq
        data = {"type": kind, "sequence_number": seq, **data}
        seq += 1
        parts.append(sse(data, event=kind))

    start = dict(body, status="in_progress", output=[], usage=None, error=None, incomplete_details=None)
    ev("response.created", response=start)
    ev("response.in_progress", response=start)
    for i, item in enumerate(body["output"]):
        added = copy.deepcopy(item)
        added["status"] = "in_progress"
        if item["type"] == "message":
            added["content"] = []
        elif item["type"] == "function_call":
            added["arguments"] = ""
        elif item["type"] == "reasoning":
            added["summary"] = []
        ev("response.output_item.added", output_index=i, item=added)
        if item["type"] == "message":
            text = item["content"][0]["text"]
            first, rest = text[:3], text[3:]
            ev("response.content_part.added", item_id=item["id"], output_index=i, content_index=0,
               part={"type": "output_text", "text": "", "annotations": []})
            ev("response.output_text.delta", item_id=item["id"], output_index=i, content_index=0, delta=first, logprobs=[])
            if scenario == "resp-error-event":
                ev("error", code="server_error", message="fake stream error", param=None)
                return stream_reply(parts, response_id=body["id"], outcome="error_event", text=[first])
            if scenario == "resp-cut":
                return stream_reply(parts, cut=True, response_id=body["id"], outcome="cut", text=[first])
            ev("response.output_text.delta", item_id=item["id"], output_index=i, content_index=0, delta=rest, logprobs=[])
            ev("response.output_text.done", item_id=item["id"], output_index=i, content_index=0, text=text, logprobs=[])
            ev("response.content_part.done", item_id=item["id"], output_index=i, content_index=0, part=item["content"][0])
        elif item["type"] == "function_call":
            args = item["arguments"]
            half = len(args) // 2
            ev("response.function_call_arguments.delta", item_id=item["id"], output_index=i, delta=args[:half])
            ev("response.function_call_arguments.delta", item_id=item["id"], output_index=i, delta=args[half:])
            ev("response.function_call_arguments.done", item_id=item["id"], output_index=i, arguments=args, name=item["name"])
        elif item["type"] == "reasoning":
            s = item["summary"][0]
            ev("response.reasoning_summary_part.added", item_id=item["id"], output_index=i, summary_index=0,
               part={"type": "summary_text", "text": ""})
            ev("response.reasoning_summary_text.delta", item_id=item["id"], output_index=i, summary_index=0, delta=s["text"])
            ev("response.reasoning_summary_text.done", item_id=item["id"], output_index=i, summary_index=0, text=s["text"])
            ev("response.reasoning_summary_part.done", item_id=item["id"], output_index=i, summary_index=0, part=s)
        ev("response.output_item.done", output_index=i, item=item)
    final = {"completed": "response.completed", "failed": "response.failed", "incomplete": "response.incomplete"}
    ev(final[body["status"]], response=body)
    return stream_reply(parts, **_facts(body))
