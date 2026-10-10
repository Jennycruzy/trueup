"""Each adapter against real span JSON saved from the sweeps (tests/fixtures/spans)."""

import json
from pathlib import Path

import pytest

from trueup.core.adapters import ADAPTERS, facts, is_llm_span, norm_finish

FIX = Path(__file__).parent / "fixtures" / "spans"


def load(lib: str, sid: str) -> dict:
    return json.loads((FIX / f"{lib}-{sid}.json").read_text())["observation"]


def llm_facts(lib: str, sid: str):
    a = ADAPTERS[lib]
    return [facts(a, s) for s in load(lib, sid)["trace"]["spans"] if is_llm_span(a, s)]


LIBS = ("neatlogs", "openinference", "openllmetry")


def test_fixtures_hold_no_local_paths_or_urls():
    for p in FIX.glob("*.json"):
        text = p.read_text()
        assert "/root" not in text and "127.0.0.1" not in text and "stacktrace" not in text, p.name


@pytest.mark.parametrize("lib", LIBS)
def test_chat_tool_calls_tokens_and_finish(lib):
    [f] = llm_facts(lib, "oa-chat-tools")
    assert (f.input_tokens, f.output_tokens) == (11, 7)
    assert [name for name, _ in f.tool_calls] == ["get_weather", "get_time"]
    args = [json.loads(a) if isinstance(a, str) else a for _, a in f.tool_calls]
    assert args == [{"city": "Lagos"}, {"tz": "WAT"}]
    assert {norm_finish(x) for x in f.finish} == {"tool_call"}


def test_response_ids_where_the_library_records_them():
    assert llm_facts("neatlogs", "oa-chat-tools")[0].response_id.startswith("chatcmpl-")
    assert llm_facts("openllmetry", "oa-chat-tools")[0].response_id.startswith("chatcmpl-")
    assert llm_facts("openinference", "oa-chat-tools")[0].response_id is None


def test_refusal_only_openllmetry_records_it():
    assert llm_facts("openllmetry", "oa-chat-refusal")[0].refusals == ("I can't help with that.",)
    for lib in ("neatlogs", "openinference"):
        f = llm_facts(lib, "oa-chat-refusal")[0]
        assert f.refusals == () and f.texts == ()


def test_openinference_reasoning_text_is_not_output_text():
    [f] = llm_facts("openinference", "oa-resp-reasoning")
    assert f.texts == ("hello",)


@pytest.mark.parametrize("lib", LIBS)
def test_responses_reasoning_tokens(lib):
    [f] = llm_facts(lib, "oa-resp-reasoning")
    assert (f.input_tokens, f.output_tokens) == (11, 7)


def test_openllmetry_error_span_without_operation_name_is_an_llm_span():
    spans = load("openllmetry", "oa-resp-stream-cut")["trace"]["spans"]
    assert "gen_ai.operation.name" not in spans[0]["attributes"]
    assert is_llm_span(ADAPTERS["openllmetry"], spans[0])


def test_openinference_anthropic_stream_tool_args():
    [f] = llm_facts("openinference", "an-stream-tools")
    assert f.tool_calls == (("get_weather", '{"city": "Lagos"}'),)
    assert "hello" in f.texts and "Need the weather." not in f.texts


def test_openllmetry_anthropic_stream_output_tokens_as_recorded():
    [f] = llm_facts("openllmetry", "an-stream-helper")
    assert (f.input_tokens, f.output_tokens) == (5, 4)


def test_finish_synonyms():
    assert norm_finish("end_turn") == "stop"
    assert norm_finish("tool_use") == norm_finish("tool_calls") == "tool_call"
    assert norm_finish("incomplete") == "length"
    assert norm_finish("failed") == "failed"
    assert norm_finish(None) is None
