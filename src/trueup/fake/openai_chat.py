"""OpenAI Chat Completions: POST /v1/chat/completions."""

from __future__ import annotations

from typing import Any

from trueup.fake.reply import Ids, Reply, json_reply, sse, stream_reply

USAGE = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
SCENARIOS = (
    "chat-plain",
    "chat-tools",
    "chat-refusal",
    "chat-n2",
    "chat-500",
    "chat-error-event",
    "chat-cut",
)
# Agent flows. The reply depends on the request, so the fake keeps no state:
# no tool result in the messages yet -> ask for a tool; tool result present -> answer.
AGENT_SCENARIOS = (
    "agent-chat",  # one tool call, then the answer
    "agent-chat-parallel",  # two tool calls in one reply, then the answer
    "agent-chat-loop",  # always asks for the tool again
    "agent-chat-fail2",  # tool call, then HTTP 500 once the tool result arrives
)
REFUSAL = "I can't help with that."
ANSWER = "It is sunny in Lagos."


def _usage_facts() -> dict[str, int]:
    return {
        "input_tokens": USAGE["prompt_tokens"],
        "output_tokens": USAGE["completion_tokens"],
        "total_tokens": USAGE["total_tokens"],
    }


def _tool_calls(ids: Ids) -> list[dict[str, Any]]:
    return [
        {
            "id": ids.new("call_"),
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"Lagos"}'},
        },
        {
            "id": ids.new("call_"),
            "type": "function",
            "function": {"name": "get_time", "arguments": '{"tz":"WAT"}'},
        },
    ]


def has_tool_result(req: dict[str, Any]) -> bool:
    return any(isinstance(m, dict) and m.get("role") == "tool" for m in req.get("messages") or [])


def _agent_tool_calls(scenario: str, ids: Ids) -> list[dict[str, Any]]:
    cities = ("Lagos", "Abuja") if scenario == "agent-chat-parallel" else ("Lagos",)
    return [
        {"id": ids.new("call_"), "type": "function",
         "function": {"name": "get_weather", "arguments": f'{{"city":"{c}"}}'}}
        for c in cities
    ]


def _choices(scenario: str, ids: Ids, req: dict[str, Any]) -> list[dict[str, Any]]:
    """The message(s) a scenario answers with, as non-streamed choices."""
    if scenario in AGENT_SCENARIOS:
        if scenario == "agent-chat-loop" or not has_tool_result(req):
            msg = {"role": "assistant", "content": None, "tool_calls": _agent_tool_calls(scenario, ids)}
            return [{"index": 0, "message": msg, "finish_reason": "tool_calls"}]
        return [{"index": 0, "message": {"role": "assistant", "content": ANSWER}, "finish_reason": "stop"}]
    if scenario == "chat-tools":
        msg = {"role": "assistant", "content": None, "tool_calls": _tool_calls(ids)}
        return [{"index": 0, "message": msg, "finish_reason": "tool_calls"}]
    if scenario == "chat-refusal":
        msg = {"role": "assistant", "content": None, "refusal": REFUSAL}
        return [{"index": 0, "message": msg, "finish_reason": "stop"}]
    if scenario == "chat-n2":
        return [
            {"index": i, "message": {"role": "assistant", "content": t}, "finish_reason": "stop"}
            for i, t in enumerate(("one", "two"))
        ]
    return [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}]


def _facts(choices: list[dict[str, Any]]) -> dict[str, Any]:
    tools = []
    for c in choices:
        for t in c["message"].get("tool_calls") or []:
            tools.append({"id": t["id"], "name": t["function"]["name"], "arguments": t["function"]["arguments"]})
    return {
        "finish": [c["finish_reason"] for c in choices],
        "tool_calls": tools,
        "text": [c["message"].get("content") or c["message"].get("refusal") or "" for c in choices],
    }


def handle(scenario: str, req: dict[str, Any], ids: Ids) -> Reply:
    if scenario == "chat-500" or (scenario == "agent-chat-fail2" and has_tool_result(req)):
        return json_reply(
            500,
            {"error": {"message": "fake server error", "type": "server_error", "code": None, "param": None}},
            outcome="http_error",
        )
    rid = ids.new("chatcmpl-")
    model = req.get("model", "")
    if not req.get("stream"):
        choices = _choices(scenario, ids, req)
        body = {
            "id": rid,
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": choices,
            "usage": USAGE,
        }
        if scenario == "chat-cut":
            raw = json_reply(200, body).body
            return Reply(200, raw[: len(raw) // 2], cut=True, response_id=rid, outcome="cut")
        if scenario == "chat-error-event":
            return json_reply(400, {"error": {"message": "chat-error-event needs stream=true", "type": "invalid_request_error"}}, outcome="http_error")
        return json_reply(200, body, response_id=rid, usage=_usage_facts(), **_facts(choices))
    return _stream(scenario, req, ids, rid, model)


def _stream(scenario: str, req: dict[str, Any], ids: Ids, rid: str, model: str) -> Reply:
    def chunk(choices: list[dict[str, Any]], usage: dict[str, int] | None = None) -> bytes:
        d: dict[str, Any] = {"id": rid, "object": "chat.completion.chunk", "created": 0, "model": model, "choices": choices}
        if usage is not None:
            d["usage"] = usage
        return sse(d)

    def delta(d: dict[str, Any], index: int = 0, finish: str | None = None) -> bytes:
        return chunk([{"index": index, "delta": d, "finish_reason": finish}])

    choices = _choices(scenario, ids, req)
    message = choices[0]["message"]
    parts = [delta({"role": "assistant", "content": ""}, i) for i in range(len(choices))]
    if scenario == "chat-tools":
        # Two parallel calls, arguments split across chunks and interleaved.
        a, b = choices[0]["message"]["tool_calls"]
        parts += [
            delta({"tool_calls": [{"index": 0, "id": a["id"], "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}),
            delta({"tool_calls": [{"index": 1, "id": b["id"], "type": "function", "function": {"name": "get_time", "arguments": ""}}]}),
            delta({"tool_calls": [{"index": 0, "function": {"arguments": '{"city":'}}]}),
            delta({"tool_calls": [{"index": 1, "function": {"arguments": '{"tz":"WAT"}'}}]}),
            delta({"tool_calls": [{"index": 0, "function": {"arguments": '"Lagos"}'}}]}),
            delta({}, 0, "tool_calls"),
        ]
    elif message.get("tool_calls"):
        # Agent tool calls: id and name first, then the arguments in two pieces.
        for i, t in enumerate(message["tool_calls"]):
            args = t["function"]["arguments"]
            parts += [
                delta({"tool_calls": [{"index": i, "id": t["id"], "type": "function",
                                       "function": {"name": t["function"]["name"], "arguments": ""}}]}),
                delta({"tool_calls": [{"index": i, "function": {"arguments": args[:5]}}]}),
                delta({"tool_calls": [{"index": i, "function": {"arguments": args[5:]}}]}),
            ]
        parts.append(delta({}, 0, "tool_calls"))
    elif scenario == "chat-refusal":
        parts += [delta({"refusal": "I can't "}), delta({"refusal": "help with that."}), delta({}, 0, "stop")]
    elif scenario == "chat-n2":
        parts += [delta({"content": "one"}, 0), delta({"content": "two"}, 1), delta({}, 0, "stop"), delta({}, 1, "stop")]
    else:
        text = message["content"]
        parts.append(delta({"content": text[:3]}))
        if scenario == "chat-error-event":
            parts.append(sse({"error": {"message": "fake stream error", "type": "server_error"}}))
            return stream_reply(parts, response_id=rid, outcome="error_event", text=[text[:3]])
        if scenario == "chat-cut":
            r = stream_reply(parts, response_id=rid, outcome="cut", text=[text[:3]])
            r.cut = True
            return r
        parts += [delta({"content": text[3:]}), delta({}, 0, "stop")]
    include_usage = bool((req.get("stream_options") or {}).get("include_usage"))
    if include_usage:
        parts.append(chunk([], usage=USAGE))
    parts.append(b"data: [DONE]\n\n")
    return stream_reply(parts, response_id=rid, usage=_usage_facts() if include_usage else None, **_facts(choices))
