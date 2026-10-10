"""App code for the framework scenarios: LangChain, LangGraph and the OpenAI Agents SDK.

Same contract as trueup.runner.apps: each function takes the fake's base URL
and the scenario's model name, returns what the app saw, and lets exceptions
propagate.

Tools record each real run in TOOL_RUNS, so the truth knows which tools ran and
which raised even when the app itself raises. The runner clears it before a
scenario and reads it after.

Every function builds its own client and agent. The Agents SDK gets its
AsyncOpenAI client through the model object, not as the SDK-wide default
client: a client kept between runs is tied to the first asyncio loop and fails
on the next one.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

TOOL_NAME = "get_weather"
QUESTION = "What is the weather in Lagos?"
TOOL_RUNS: list[dict[str, str]] = []


def _weather(city: str) -> str:
    TOOL_RUNS.append({"name": TOOL_NAME, "outcome": "ok"})
    return f"Sunny in {city}"


def _weather_broken(city: str) -> str:
    TOOL_RUNS.append({"name": TOOL_NAME, "outcome": "raised"})
    raise RuntimeError("weather service down")


# LangChain and LangGraph (Chat Completions through ChatOpenAI)


def _chat_model(base: str, model: str, **kw: Any):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, api_key="trueup-fake", base_url=f"{base}/v1", max_retries=0, **kw)


def _lc_tool(broken: bool = False):
    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        _weather_broken if broken else _weather, name=TOOL_NAME, description="Get the weather for a city."
    )


def lc_invoke(base: str, model: str) -> dict[str, Any]:
    m = _chat_model(base, model).invoke(QUESTION)
    return {"text": m.content, "refusal": m.additional_kwargs.get("refusal")}


def lc_stream(base: str, model: str) -> dict[str, Any]:
    text = ""
    for chunk in _chat_model(base, model, stream_usage=True).stream(QUESTION):
        text += chunk.content if isinstance(chunk.content, str) else ""
    return {"text": text}


def _react(base: str, model: str, broken: bool = False):
    from langgraph.prebuilt import create_react_agent

    return create_react_agent(_chat_model(base, model), [_lc_tool(broken)])


def _last_text(state: dict[str, Any]) -> str:
    return state["messages"][-1].content


def lg_agent(base: str, model: str) -> dict[str, Any]:
    return {"answer": _last_text(_react(base, model).invoke({"messages": [("user", QUESTION)]}))}


def lg_agent_tool_raises(base: str, model: str) -> dict[str, Any]:
    return {"answer": _last_text(_react(base, model, broken=True).invoke({"messages": [("user", QUESTION)]}))}


def lg_agent_step_limit(base: str, model: str) -> dict[str, Any]:
    g = _react(base, model)
    return {"answer": _last_text(g.invoke({"messages": [("user", QUESTION)]}, config={"recursion_limit": 6}))}


def lg_agent_stream(base: str, model: str) -> dict[str, Any]:
    text = ""
    for chunk, _meta in _react(base, model).stream({"messages": [("user", QUESTION)]}, stream_mode="messages"):
        if chunk.type == "AIMessageChunk" and isinstance(chunk.content, str):
            text += chunk.content
    return {"answer": text}


# OpenAI Agents SDK (Responses API)


def _agent(base: str, model: str, broken: bool = False):
    from agents import Agent, OpenAIResponsesModel, function_tool
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key="trueup-fake", base_url=f"{base}/v1", max_retries=0)
    tool = function_tool(_weather_broken if broken else _weather, name_override=TOOL_NAME)
    return Agent(name="helper", instructions="Answer with the tool.", tools=[tool],
                 model=OpenAIResponsesModel(model=model, openai_client=client))


def _ag_run(base: str, model: str, broken: bool = False, max_turns: int = 10) -> dict[str, Any]:
    from agents import Runner

    r = Runner.run_sync(_agent(base, model, broken), QUESTION, max_turns=max_turns)
    return {"answer": r.final_output}


def ag_run(base: str, model: str) -> dict[str, Any]:
    return _ag_run(base, model)


def ag_run_tool_raises(base: str, model: str) -> dict[str, Any]:
    return _ag_run(base, model, broken=True)


def ag_run_max_turns(base: str, model: str) -> dict[str, Any]:
    return _ag_run(base, model, max_turns=3)


def ag_run_streamed(base: str, model: str) -> dict[str, Any]:
    from agents import Runner

    async def go() -> dict[str, Any]:
        r = Runner.run_streamed(_agent(base, model), QUESTION)
        events = 0
        async for _ in r.stream_events():
            events += 1
        return {"answer": r.final_output, "events": events}

    return asyncio.run(go())


FRAMEWORK_APPS: dict[str, Callable[[str, str], dict[str, Any]]] = {
    name: fn
    for name, fn in dict(globals()).items()
    if callable(fn) and name.startswith(("lc_", "lg_", "ag_")) and getattr(fn, "__module__", None) == __name__
}
