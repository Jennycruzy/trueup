"""The fake's agent flows, parsed by the real openai SDK, LangChain and the OpenAI Agents SDK.

The fake picks each reply from the request: no tool result yet -> a tool call;
tool result present -> the answer (or the scenario's failure).
"""

import json

import openai
import pytest

from trueup.fake import FakeProvider
from trueup.fake.openai_chat import ANSWER
from trueup.fake.openai_responses import UNKNOWN_TOOL
from trueup.runner import framework_apps

Q = [{"role": "user", "content": "weather?"}]
TOOLS = [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}]
RESP_TOOLS = [{"type": "function", "name": "get_weather", "parameters": {"type": "object"}}]


@pytest.fixture
def fake():
    with FakeProvider() as f:
        yield f


@pytest.fixture
def oc(fake):
    return openai.OpenAI(api_key="x", base_url=fake.openai_base_url, max_retries=0)


def _after_tool(msg, call_ids):
    return Q + [msg.model_dump(exclude_none=True)] + [
        {"role": "tool", "tool_call_id": cid, "content": "Sunny"} for cid in call_ids
    ]


# Chat Completions agent flows


def test_chat_agent_tool_call_then_answer(fake, oc):
    r1 = oc.chat.completions.create(model="agent-chat", messages=Q, tools=TOOLS)
    (tc,) = r1.choices[0].message.tool_calls
    assert (tc.function.name, json.loads(tc.function.arguments)) == ("get_weather", {"city": "Lagos"})
    assert r1.choices[0].finish_reason == "tool_calls"
    r2 = oc.chat.completions.create(model="agent-chat", messages=_after_tool(r1.choices[0].message, [tc.id]))
    assert r2.choices[0].message.content == ANSWER and r2.choices[0].finish_reason == "stop"
    log = fake.log.entries()
    assert [e["outcome"] for e in log] == ["complete", "complete"]
    assert [len(e["tool_calls"]) for e in log] == [1, 0] and log[1]["text"] == [ANSWER]


def test_chat_agent_parallel_tools(fake, oc):
    r = oc.chat.completions.create(model="agent-chat-parallel", messages=Q, tools=TOOLS)
    args = [json.loads(t.function.arguments)["city"] for t in r.choices[0].message.tool_calls]
    assert args == ["Lagos", "Abuja"]
    assert len({t.id for t in r.choices[0].message.tool_calls}) == 2


def test_chat_agent_loop_keeps_calling(fake, oc):
    r1 = oc.chat.completions.create(model="agent-chat-loop", messages=Q, tools=TOOLS)
    tc = r1.choices[0].message.tool_calls[0]
    r2 = oc.chat.completions.create(model="agent-chat-loop", messages=_after_tool(r1.choices[0].message, [tc.id]))
    assert r2.choices[0].message.tool_calls and r2.choices[0].message.tool_calls[0].id != tc.id


def test_chat_agent_fails_on_second_call(fake, oc):
    r1 = oc.chat.completions.create(model="agent-chat-fail2", messages=Q, tools=TOOLS)
    tc = r1.choices[0].message.tool_calls[0]
    with pytest.raises(openai.InternalServerError):
        oc.chat.completions.create(model="agent-chat-fail2", messages=_after_tool(r1.choices[0].message, [tc.id]))
    assert [e["outcome"] for e in fake.log.entries()] == ["complete", "http_error"]


def test_chat_agent_streamed_tool_call_arguments_join(fake, oc):
    calls, finish = {}, None
    for ch in oc.chat.completions.create(model="agent-chat-parallel", messages=Q, tools=TOOLS, stream=True):
        for c in ch.choices:
            finish = c.finish_reason or finish
            for t in c.delta.tool_calls or []:
                d = calls.setdefault(t.index, {"name": "", "args": ""})
                d["name"] += t.function.name or ""
                d["args"] += t.function.arguments or ""
    assert [json.loads(d["args"]) for d in calls.values()] == [{"city": "Lagos"}, {"city": "Abuja"}]
    assert finish == "tool_calls"
    (e,) = fake.log.entries()
    assert [t["arguments"] for t in e["tool_calls"]] == ['{"city":"Lagos"}', '{"city":"Abuja"}']


def test_chat_agent_streamed_answer(fake, oc):
    msgs = Q + [{"role": "tool", "tool_call_id": "call_x", "content": "Sunny"}]
    text = "".join(c.delta.content or "" for ch in oc.chat.completions.create(
        model="agent-chat", messages=msgs, stream=True) for c in ch.choices)
    assert text == ANSWER


# Responses agent flows


def _resp_after_tool(r):
    fc = r.output[0]
    return [{"role": "user", "content": "weather?"}, fc.model_dump(exclude_none=True),
            {"type": "function_call_output", "call_id": fc.call_id, "output": "Sunny"}]


def test_resp_agent_tool_call_then_answer(fake, oc):
    r1 = oc.responses.create(model="agent-resp", input="weather?", tools=RESP_TOOLS)
    assert [o.type for o in r1.output] == ["function_call"] and r1.output[0].name == "get_weather"
    r2 = oc.responses.create(model="agent-resp", input=_resp_after_tool(r1), tools=RESP_TOOLS)
    assert r2.output_text == ANSWER
    assert [e["outcome"] for e in fake.log.entries()] == ["complete", "complete"]


def test_resp_agent_loop_and_unknown_tool(fake, oc):
    r1 = oc.responses.create(model="agent-resp-loop", input="weather?")
    r2 = oc.responses.create(model="agent-resp-loop", input=_resp_after_tool(r1))
    assert r2.output[0].type == "function_call"
    bad = oc.responses.create(model="agent-resp-badtool", input="weather?")
    assert bad.output[0].name == UNKNOWN_TOOL


def test_resp_agent_fails_on_second_call(fake, oc):
    r1 = oc.responses.create(model="agent-resp-fail2", input="weather?")
    with pytest.raises(openai.InternalServerError):
        oc.responses.create(model="agent-resp-fail2", input=_resp_after_tool(r1))


FULL_TEXT_STREAM = [
    "response.created", "response.in_progress", "response.output_item.added", "response.content_part.added",
    "response.output_text.delta", "response.output_text.delta", "response.output_text.done",
    "response.content_part.done", "response.output_item.done", "response.completed",
]
FULL_TOOL_STREAM = [
    "response.created", "response.in_progress", "response.output_item.added",
    "response.function_call_arguments.delta", "response.function_call_arguments.delta",
    "response.function_call_arguments.done", "response.output_item.done", "response.completed",
]


def test_resp_agent_stream_full_event_sequence(fake, oc):
    first = list(oc.responses.create(model="agent-resp", input="weather?", stream=True))
    assert [e.type for e in first] == FULL_TOOL_STREAM
    assert [e.sequence_number for e in first] == list(range(len(first)))
    fc = first[-1].response.output[0]
    second = list(oc.responses.create(model="agent-resp", stream=True, input=[
        fc.model_dump(exclude_none=True), {"type": "function_call_output", "call_id": fc.call_id, "output": "Sunny"}]))
    assert [e.type for e in second] == FULL_TEXT_STREAM
    assert second[-1].response.output_text == ANSWER and second[-1].response.usage.total_tokens == 18


def _second_stream(oc, model):
    first = list(oc.responses.create(model=model, input="weather?", stream=True))
    fc = first[-1].response.output[0]
    return oc.responses.create(model=model, stream=True, input=[
        fc.model_dump(exclude_none=True), {"type": "function_call_output", "call_id": fc.call_id, "output": "Sunny"}])


def test_resp_agent_stream_error_event_only_on_answer(fake, oc):
    types = [e.type for e in _second_stream(oc, "agent-resp-error-event")]
    assert types[-1] == "error" and "response.completed" not in types
    assert [e["outcome"] for e in fake.log.entries()] == ["complete", "error_event"]


def test_resp_agent_stream_cut_only_on_answer(fake, oc):
    with pytest.raises(openai.APIConnectionError):
        list(_second_stream(oc, "agent-resp-cut"))
    assert [e["outcome"] for e in fake.log.entries()] == ["complete", "cut"]


# Through the frameworks


def test_agents_sdk_streamed_run_reads_full_sequence(fake):
    framework_apps.TOOL_RUNS.clear()
    out = framework_apps.ag_run_streamed(fake.base_url, "agent-resp")
    assert out["answer"] == ANSWER and out["events"] > 10
    assert framework_apps.TOOL_RUNS == [{"name": "get_weather", "outcome": "ok"}]
    assert [e["stream"] for e in fake.log.entries()] == [True, True]


def test_agents_sdk_unknown_tool_raises_and_runs_nothing(fake):
    from agents.exceptions import ModelBehaviorError

    framework_apps.TOOL_RUNS.clear()
    with pytest.raises(ModelBehaviorError, match=UNKNOWN_TOOL):
        framework_apps.ag_run(fake.base_url, "agent-resp-badtool")
    assert framework_apps.TOOL_RUNS == []


def test_langgraph_parallel_tools_both_run(fake):
    framework_apps.TOOL_RUNS.clear()
    assert framework_apps.lg_agent(fake.base_url, "agent-chat-parallel")["answer"] == ANSWER
    assert len(framework_apps.TOOL_RUNS) == 2
