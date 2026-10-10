"""The fake parsed by the real openai and anthropic SDKs.

Each test checks that the SDK accepts what the fake sends, that the values the
app sees match, and that the truth log records the call.
"""

import asyncio
import json

import anthropic
import openai
import pytest

from trueup.fake import FakeProvider

M = [{"role": "user", "content": "hi"}]


@pytest.fixture
def fake():
    with FakeProvider() as f:
        yield f


@pytest.fixture
def oc(fake):
    return openai.OpenAI(api_key="x", base_url=fake.openai_base_url, max_retries=0)


@pytest.fixture
def ac(fake):
    return anthropic.Anthropic(api_key="x", base_url=fake.base_url, max_retries=0)


def only(fake):
    entries = fake.log.entries()
    assert len(entries) == 1
    return entries[0]


# OpenAI Chat Completions


def test_chat_plain(fake, oc):
    r = oc.chat.completions.create(model="chat-plain", messages=M)
    assert r.choices[0].message.content == "hello"
    assert r.choices[0].finish_reason == "stop"
    assert (r.usage.prompt_tokens, r.usage.completion_tokens, r.usage.total_tokens) == (11, 7, 18)
    e = only(fake)
    assert e["response_id"] == r.id
    assert e["usage"] == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert e["api"] == "openai.chat" and e["outcome"] == "complete"


def test_chat_stream_with_usage(fake, oc):
    text, usage, ids = "", None, set()
    for ch in oc.chat.completions.create(
        model="chat-plain", messages=M, stream=True, stream_options={"include_usage": True}
    ):
        ids.add(ch.id)
        usage = ch.usage or usage
        for c in ch.choices:
            text += c.delta.content or ""
    assert text == "hello"
    assert usage.total_tokens == 18
    e = only(fake)
    assert ids == {e["response_id"]}
    assert e["usage_sent"] and e["include_usage"]


def test_chat_stream_without_usage(fake, oc):
    chunks = list(oc.chat.completions.create(model="chat-plain", messages=M, stream=True))
    assert all(ch.usage is None for ch in chunks)
    assert "".join(c.delta.content or "" for ch in chunks for c in ch.choices) == "hello"
    e = only(fake)
    assert e["usage"] is None and e["usage_sent"] is False


def test_chat_two_parallel_tool_calls(fake, oc):
    r = oc.chat.completions.create(model="chat-tools", messages=M)
    calls = r.choices[0].message.tool_calls
    assert [(c.function.name, json.loads(c.function.arguments)) for c in calls] == [
        ("get_weather", {"city": "Lagos"}),
        ("get_time", {"tz": "WAT"}),
    ]
    assert r.choices[0].finish_reason == "tool_calls"
    assert calls[0].id != calls[1].id
    assert [t["id"] for t in only(fake)["tool_calls"]] == [c.id for c in calls]


def test_chat_stream_tool_calls_split_arguments(fake, oc):
    calls, finish = {}, None
    for ch in oc.chat.completions.create(model="chat-tools", messages=M, stream=True):
        for c in ch.choices:
            finish = c.finish_reason or finish
            for tc in c.delta.tool_calls or []:
                d = calls.setdefault(tc.index, {"id": None, "name": "", "args": ""})
                d["id"] = tc.id or d["id"]
                d["name"] += tc.function.name or ""
                d["args"] += tc.function.arguments or ""
    assert finish == "tool_calls"
    assert [(d["name"], json.loads(d["args"])) for d in calls.values()] == [
        ("get_weather", {"city": "Lagos"}),
        ("get_time", {"tz": "WAT"}),
    ]
    assert [t["arguments"] for t in only(fake)["tool_calls"]] == [d["args"] for d in calls.values()]


def test_chat_refusal(fake, oc):
    r = oc.chat.completions.create(model="chat-refusal", messages=M)
    assert r.choices[0].message.content is None
    assert r.choices[0].message.refusal == "I can't help with that."
    chunks = list(oc.chat.completions.create(model="chat-refusal", messages=M, stream=True))
    assert "".join(c.delta.refusal or "" for ch in chunks for c in ch.choices) == "I can't help with that."


def test_chat_n2(fake, oc):
    r = oc.chat.completions.create(model="chat-n2", messages=M, n=2)
    assert [c.message.content for c in r.choices] == ["one", "two"]
    assert only(fake)["n"] == 2


def test_chat_http_500_raises_sdk_error(fake, oc):
    with pytest.raises(openai.InternalServerError) as e:
        oc.chat.completions.create(model="chat-500", messages=M)
    assert e.value.status_code == 500
    assert only(fake)["outcome"] == "http_error"


def test_chat_error_event_mid_stream_raises_sdk_error(fake, oc):
    text = ""
    with pytest.raises(openai.APIError, match="fake stream error"):
        for ch in oc.chat.completions.create(model="chat-error-event", messages=M, stream=True):
            for c in ch.choices:
                text += c.delta.content or ""
    assert text == "hel"
    assert only(fake)["outcome"] == "error_event"


def test_chat_dropped_connection_raises_sdk_error(fake, oc):
    with pytest.raises(openai.APIConnectionError):
        for _ in oc.chat.completions.create(model="chat-cut", messages=M, stream=True):
            pass
    with pytest.raises(openai.APIConnectionError):
        oc.chat.completions.create(model="chat-cut", messages=M)
    assert [e["outcome"] for e in fake.log.entries()] == ["cut", "cut"]


# OpenAI Responses


def test_responses_plain(fake, oc):
    r = oc.responses.create(model="resp-plain", input="hi")
    assert r.status == "completed" and r.output_text == "hello"
    assert (r.usage.input_tokens, r.usage.output_tokens) == (11, 7)
    assert only(fake)["response_id"] == r.id


def test_responses_function_call(fake, oc):
    r = oc.responses.create(model="resp-tool", input="hi")
    (fc,) = r.output
    assert fc.type == "function_call" and fc.name == "get_weather"
    assert json.loads(fc.arguments) == {"city": "Lagos"}
    assert only(fake)["tool_calls"][0]["id"] == fc.call_id


def test_responses_reasoning_summary(fake, oc):
    r = oc.responses.create(model="resp-reasoning", input="hi")
    assert [o.type for o in r.output] == ["reasoning", "message"]
    assert r.output[0].summary[0].text == "Think about the weather."
    assert r.usage.output_tokens_details.reasoning_tokens == 4
    assert only(fake)["usage"]["reasoning_tokens"] == 4


def test_responses_failed(fake, oc):
    r = oc.responses.create(model="resp-failed", input="hi")
    assert r.status == "failed" and r.error.code == "server_error"
    assert r.output == []
    assert only(fake)["outcome"] == "failed"


def test_responses_incomplete(fake, oc):
    r = oc.responses.create(model="resp-incomplete", input="hi")
    assert r.status == "incomplete"
    assert r.incomplete_details.reason == "max_output_tokens"
    assert r.output_text == "The answer is cut"


@pytest.mark.parametrize("scenario", ["resp-plain", "resp-tool", "resp-reasoning"])
def test_responses_stream_helper_matches_plain(fake, oc, scenario):
    plain = oc.responses.create(model=scenario, input="hi")
    with oc.responses.stream(model=scenario, input="hi") as s:
        types = [ev.type for ev in s]
        final = s.get_final_response()
    assert types[:2] == ["response.created", "response.in_progress"]
    assert types[-1] == "response.completed"
    assert [o.type for o in final.output] == [o.type for o in plain.output]
    assert final.output_text == plain.output_text
    assert final.usage.total_tokens == 18
    assert final.id != plain.id


def test_responses_stream_sequence_numbers_increase(fake, oc):
    seqs = [ev.sequence_number for ev in oc.responses.create(model="resp-reasoning", input="hi", stream=True)]
    assert seqs == list(range(len(seqs)))


@pytest.mark.parametrize(("scenario", "last"), [("resp-failed", "response.failed"), ("resp-incomplete", "response.incomplete")])
def test_responses_stream_terminal_status(fake, oc, scenario, last):
    events = list(oc.responses.create(model=scenario, input="hi", stream=True))
    assert events[-1].type == last
    assert events[-1].response.status == scenario.removeprefix("resp-")


def test_responses_stream_error_event_reaches_app(fake, oc):
    # The openai SDK does not raise on a Responses `error` event; it hands
    # the event to the app. Truth records it as an error.
    events = list(oc.responses.create(model="resp-error-event", input="hi", stream=True))
    assert events[-1].type == "error"
    assert events[-1].message == "fake stream error"
    assert only(fake)["outcome"] == "error_event"


def test_responses_stream_cut_raises_sdk_error(fake, oc):
    with pytest.raises(openai.APIConnectionError):
        for _ in oc.responses.create(model="resp-cut", input="hi", stream=True):
            pass
    assert only(fake)["outcome"] == "cut"


# Anthropic Messages


def test_anthropic_plain(fake, ac):
    r = ac.messages.create(model="anth-plain", max_tokens=50, messages=M)
    assert r.content[0].text == "hello" and r.stop_reason == "end_turn"
    assert (r.usage.input_tokens, r.usage.output_tokens) == (5, 3)
    assert only(fake)["response_id"] == r.id


def test_anthropic_thinking(fake, ac):
    r = ac.messages.create(model="anth-thinking", max_tokens=50, messages=M)
    assert [b.type for b in r.content] == ["thinking", "text"]
    assert r.content[0].thinking == "Need the weather."


def test_anthropic_stream_helper(fake, ac):
    with ac.messages.stream(model="anth-thinking", max_tokens=50, messages=M) as s:
        text = "".join(s.text_stream)
        final = s.get_final_message()
    assert text == "hello"
    assert [b.type for b in final.content] == ["thinking", "text"]
    assert final.content[0].signature == "fake-sig"
    assert (final.usage.input_tokens, final.usage.output_tokens) == (5, 3)
    assert only(fake)["response_id"] == final.id


def test_anthropic_tool_use_input_json_delta(fake, ac):
    with ac.messages.stream(model="anth-tools", max_tokens=50, messages=M) as s:
        final = s.get_final_message()
    tool = final.content[-1]
    assert tool.type == "tool_use" and tool.name == "get_weather"
    assert tool.input == {"city": "Lagos"}
    assert final.stop_reason == "tool_use"
    plain = ac.messages.create(model="anth-tools", max_tokens=50, messages=M)
    assert plain.content[-1].input == {"city": "Lagos"}
    assert plain.content[-1].id != tool.id


def test_anthropic_raw_stream_events(fake, ac):
    types = [ev.type for ev in ac.messages.create(model="anth-plain", max_tokens=50, messages=M, stream=True)]
    assert types[0] == "message_start" and types[-1] == "message_stop"


def test_anthropic_error_event_raises_sdk_error(fake, ac):
    with pytest.raises(anthropic.APIStatusError, match="Overloaded"):
        for _ in ac.messages.create(model="anth-error-event", max_tokens=50, messages=M, stream=True):
            pass
    assert only(fake)["outcome"] == "error_event"


def test_anthropic_cut_raises(fake, ac):
    # The anthropic SDK does not wrap a dropped stream: the transport's
    # RemoteProtocolError reaches the app. Recorded as a fact, not hidden.
    with pytest.raises(Exception) as e:
        for _ in ac.messages.create(model="anth-cut", max_tokens=50, messages=M, stream=True):
            pass
    assert type(e.value).__name__ == "RemoteProtocolError"
    with pytest.raises(anthropic.APIConnectionError):
        ac.messages.create(model="anth-cut", max_tokens=50, messages=M)


def test_anthropic_529_raises_sdk_error(fake, ac):
    with pytest.raises(anthropic.OverloadedError) as e:
        ac.messages.create(model="anth-529", max_tokens=50, messages=M)
    assert e.value.status_code == 529


def test_anthropic_async(fake):
    async def go():
        async with anthropic.AsyncAnthropic(api_key="x", base_url=fake.base_url, max_retries=0) as c:
            return await c.messages.create(model="anth-plain", max_tokens=50, messages=M)

    assert asyncio.run(go()).content[0].text == "hello"


# Truth log


def test_truth_log_counts_calls_and_tokens(fake, oc, ac):
    oc.chat.completions.create(model="chat-plain", messages=M)
    oc.responses.create(model="resp-plain", input="hi")
    ac.messages.create(model="anth-plain", max_tokens=50, messages=M)
    s = fake.log.summary()
    assert s["calls"] == 3
    assert [u["total_tokens"] for u in s["tokens_per_call"]] == [18, 18, 8]
    assert [e["seq"] for e in fake.log.entries()] == [1, 2, 3]


def test_unknown_route_is_404_and_logged(fake, oc):
    with pytest.raises(openai.NotFoundError):
        oc.embeddings.create(model="x", input="hi")
    assert only(fake)["api"] == "unknown"
