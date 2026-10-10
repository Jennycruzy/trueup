"""App code for each scenario: plain SDK calls, the way an app would write them.

Each function takes the fake's base URL and the scenario's model name and
returns what the app saw. Exceptions are left to propagate; the runner records
them as the app outcome.

Every function builds its own client. Reusing one async client across two
asyncio.run() loops fails with "Event loop is closed" on the second loop, which
would show up as a false app error.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

M = [{"role": "user", "content": "What is the weather in Lagos?"}]
OA_TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_time", "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}}}},
]
RESP_TOOLS = [{"type": "function", "name": "get_weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}]
AN_TOOLS = [{"name": "get_weather", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}]


def _oa(base: str):
    import openai

    return openai.OpenAI(api_key="trueup-fake", base_url=f"{base}/v1", max_retries=0)


def _an(base: str):
    import anthropic

    return anthropic.Anthropic(api_key="trueup-fake", base_url=base, max_retries=0)


# OpenAI Chat Completions


def chat_create(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        r = c.chat.completions.create(model=model, messages=M)
    m = r.choices[0].message
    return {"text": m.content, "refusal": m.refusal, "finish": r.choices[0].finish_reason, "total_tokens": r.usage.total_tokens}


def chat_create_tools(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        r = c.chat.completions.create(model=model, messages=M, tools=OA_TOOLS)
    calls = r.choices[0].message.tool_calls or []
    return {"tool_calls": [{"name": t.function.name, "arguments": t.function.arguments} for t in calls]}


def chat_create_n2(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        r = c.chat.completions.create(model=model, messages=M, n=2)
    return {"choices": [ch.message.content for ch in r.choices]}


def _read_chat_stream(stream) -> dict[str, Any]:
    out: dict[str, Any] = {"text": "", "tool_calls": {}, "finish": None, "total_tokens": None}
    for ch in stream:
        if ch.usage:
            out["total_tokens"] = ch.usage.total_tokens
        for c in ch.choices:
            out["text"] += c.delta.content or ""
            out["finish"] = c.finish_reason or out["finish"]
            for tc in c.delta.tool_calls or []:
                d = out["tool_calls"].setdefault(str(tc.index), {"name": "", "arguments": ""})
                d["name"] += tc.function.name or ""
                d["arguments"] += tc.function.arguments or ""
    out["tool_calls"] = list(out["tool_calls"].values())
    return out


def chat_stream(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        return _read_chat_stream(c.chat.completions.create(model=model, messages=M, stream=True))


def chat_stream_usage(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        return _read_chat_stream(
            c.chat.completions.create(model=model, messages=M, stream=True, stream_options={"include_usage": True})
        )


def chat_stream_tools(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        return _read_chat_stream(c.chat.completions.create(model=model, messages=M, tools=OA_TOOLS, stream=True))


def chat_stream_break(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        s = c.chat.completions.create(model=model, messages=M, stream=True)
        chunks = 0
        for _ in s:
            chunks += 1
            break
        s.close()
    return {"chunks_read": chunks}


def chat_async_stream(base: str, model: str) -> dict[str, Any]:
    import openai

    async def go() -> dict[str, Any]:
        text, tokens = "", None
        async with openai.AsyncOpenAI(api_key="trueup-fake", base_url=f"{base}/v1", max_retries=0) as c:
            stream = await c.chat.completions.create(
                model=model, messages=M, stream=True, stream_options={"include_usage": True}
            )
            async for ch in stream:
                if ch.usage:
                    tokens = ch.usage.total_tokens
                for x in ch.choices:
                    text += x.delta.content or ""
        return {"text": text, "total_tokens": tokens}

    return asyncio.run(go())


# OpenAI Responses


def resp_create(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        r = c.responses.create(model=model, input="What is the weather in Lagos?", tools=RESP_TOOLS)
    return {
        "status": r.status,
        "output_types": [o.type for o in r.output],
        "text": r.output_text,
        "total_tokens": r.usage.total_tokens if r.usage else None,
    }


def resp_stream(base: str, model: str) -> dict[str, Any]:
    with _oa(base) as c:
        with c.responses.stream(model=model, input="What is the weather in Lagos?", tools=RESP_TOOLS) as s:
            for _ in s:
                pass
            r = s.get_final_response()
    return {"status": r.status, "output_types": [o.type for o in r.output], "text": r.output_text}


def resp_stream_raw(base: str, model: str) -> dict[str, Any]:
    # The SDK yields a Responses `error` event instead of raising; an app
    # that checks for it raises its own error, which is what we do here.
    with _oa(base) as c:
        types = []
        for ev in c.responses.create(model=model, input="hi", stream=True):
            types.append(ev.type)
            if ev.type == "error":
                raise RuntimeError(f"stream error event: {ev.message}")
    return {"events": types}


# Anthropic Messages


def an_create(base: str, model: str) -> dict[str, Any]:
    with _an(base) as c:
        r = c.messages.create(model=model, max_tokens=64, messages=M)
    return {"blocks": [b.type for b in r.content], "stop_reason": r.stop_reason}


def an_stream_helper(base: str, model: str, **kw: Any) -> dict[str, Any]:
    with _an(base) as c:
        with c.messages.stream(model=model, max_tokens=64, messages=M, **kw) as s:
            text = "".join(s.text_stream)
            fm = s.get_final_message()
    return {
        "text": text,
        "blocks": [b.type for b in fm.content],
        "tool_inputs": [b.input for b in fm.content if b.type == "tool_use"],
        "usage": [fm.usage.input_tokens, fm.usage.output_tokens],
    }


def an_stream_helper_tools(base: str, model: str) -> dict[str, Any]:
    return an_stream_helper(base, model, tools=AN_TOOLS)


def an_create_stream(base: str, model: str) -> dict[str, Any]:
    with _an(base) as c:
        text = ""
        for ev in c.messages.create(model=model, max_tokens=64, messages=M, stream=True):
            if ev.type == "content_block_delta" and ev.delta.type == "text_delta":
                text += ev.delta.text
    return {"text": text}


def an_async_create(base: str, model: str) -> dict[str, Any]:
    import anthropic

    async def go() -> dict[str, Any]:
        async with anthropic.AsyncAnthropic(api_key="trueup-fake", base_url=base, max_retries=0) as c:
            r = await c.messages.create(model=model, max_tokens=64, messages=M)
        return {"text": r.content[0].text}

    return asyncio.run(go())


APPS: dict[str, Callable[[str, str], dict[str, Any]]] = {
    name: fn
    for name, fn in dict(globals()).items()
    if callable(fn) and not name.startswith("_") and getattr(fn, "__module__", None) == __name__
}

# Framework apps live in their own module; the framework packages are imported lazily.
from trueup.runner.framework_apps import FRAMEWORK_APPS  # noqa: E402

APPS.update(FRAMEWORK_APPS)
