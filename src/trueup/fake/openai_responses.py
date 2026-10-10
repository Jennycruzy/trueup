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
# Agent flows (OpenAI Agents SDK). Stateless, like the chat ones: no
# function_call_output in the input yet -> call a tool; present -> answer.
AGENT_SCENARIOS = (
    "agent-resp",  # one tool call, then the answer
    "agent-resp-loop",  # always calls the tool again
    "agent-resp-fail2",  # tool call, then HTTP 500 once the tool output arrives
    "agent-resp-badtool",  # calls a tool the agent does not have
    "agent-resp-error-event",  # tool call, then an error event in the answer stream
    "agent-resp-cut",  # tool call, then the connection drops in the answer stream
)
ANSWER = "It is sunny in Lagos."
UNKNOWN_TOOL = "no_such_tool"
ERROR_EVENT = ("resp-error-event", "agent-resp-error-event")
CUT = ("resp-cut", "agent-resp-cut")
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


def has_tool_output(req: dict[str, Any]) -> bool:
    inp = req.get("input")
    return isinstance(inp, list) and any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in inp)


def _function_call(ids: Ids, name: str = "get_weather") -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": ids.new("fc_"),
        "call_id": ids.new("call_"),
        "name": name,
        "arguments": '{"city":"Lagos"}',
        "status": "completed",
    }


def _body(scenario: str, model: str, ids: Ids, req: dict[str, Any]) -> dict[str, Any]:
    reasoning = 0
    status = "completed"
    error = None
    incomplete = None
    if scenario in AGENT_SCENARIOS:
        if scenario == "agent-resp-loop" or not has_tool_output(req):
            output = [_function_call(ids, UNKNOWN_TOOL if scenario == "agent-resp-badtool" else "get_weather")]
        else:
            output = [_message(ids, ANSWER)]
    elif scenario == "resp-tool":
        output = [_function_call(ids)]
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
    if scenario == "agent-resp-fail2" and has_tool_output(req):
        return json_reply(
            500,
            {"error": {"message": "fake server error", "type": "server_error", "code": None, "param": None}},
            outcome="http_error",
        )
    body = _body(scenario, req.get("model", ""), ids, req)
    # Agent error and cut scenarios fail only on the answer (after the tool ran).
    fails_here = scenario.startswith("resp-") or has_tool_output(req)
    if not req.get("stream"):
        if scenario in CUT and fails_here:
            raw = json.dumps(body).encode()
            return Reply(200, raw[: len(raw) // 2], cut=True, response_id=body["id"], outcome="cut")
        if scenario in ERROR_EVENT and fails_here:
            return json_reply(400, {"error": {"message": f"{scenario} needs stream=true", "type": "invalid_request_error"}}, outcome="http_error")
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
            if scenario in ERROR_EVENT:
                ev("error", code="server_error", message="fake stream error", param=None)
                return stream_reply(parts, response_id=body["id"], outcome="error_event", text=[first])
            if scenario in CUT:
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
