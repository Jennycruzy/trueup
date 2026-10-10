"""The comparer: synthetic observations for each check, plus real fixtures."""

import json
from pathlib import Path

import pytest

from trueup.core.compare import compare, leads, match_calls, top_level
from trueup.core.adapters import ADAPTERS, facts
from trueup.core.model import Observation, Severity

FIX = Path(__file__).parent / "fixtures" / "spans"


def call(outcome="complete", usage=(11, 7), text=("hello",), finish=("stop",), tools=(), rid="chatcmpl-1", **kw):
    return {
        "response_id": rid,
        "outcome": outcome,
        "usage": None if usage is None else {"input_tokens": usage[0], "output_tokens": usage[1]},
        "usage_sent": usage is not None,
        "text": list(text),
        "finish": list(finish),
        "tool_calls": [{"name": n, "arguments": a} for n, a in tools],
        "include_usage": False,
        **kw,
    }


def span(sid="s1", parent=None, code="UNSET", attrs=None, events=(), start=1):
    base = {"neatlogs.span.kind": "llm", "neatlogs.llm.response_id": "chatcmpl-1",
            "neatlogs.llm.token_count.prompt": 11, "neatlogs.llm.token_count.completion": 7,
            "neatlogs.llm.finish_reason": "stop", "neatlogs.llm.output_messages.0.content": "hello"}
    return {"name": "openai.chat.completions.create", "span_id": sid, "parent_id": parent, "start_ns": start,
            "status": {"code": code, "description": None}, "attributes": {**base, **(attrs or {})},
            "events": [{"name": e, "attributes": {}} for e in events]}


def obs(calls, spans, outcome="ok", exception=None, expected=None, result=None):
    truth = {"fake_log": calls, "outcome": outcome, "app": {"outcome": outcome, "result": result}}
    if exception:
        truth["exception"] = exception
    if expected is not None:
        truth["expected"] = expected
    return Observation(truth=truth, trace={"library": "neatlogs", "spans": spans})


def checks(o):
    return sorted((m.check, m.severity) for m in compare(o))


def test_clean_run_has_no_mismatches():
    assert compare(obs([call()], [span()])) == []


def test_crash_shown_as_ok_is_high():
    o = obs([call("http_error", usage=None, text=(), finish=())], [span(code="OK", events=("exception",))],
            outcome="exception", exception="InternalServerError")
    assert ("run_status", Severity.HIGH) in checks(o)


def test_error_on_a_successful_run_is_high_but_not_for_failed_responses():
    assert ("run_status", Severity.HIGH) in checks(obs([call()], [span(code="ERROR")]))
    failed = call("failed", usage=None, text=(), finish=("failed",))
    assert checks(obs([failed], [span(code="ERROR")])) == []


def test_run_status_uses_top_level_span_only():
    parent = {**span("p"), "attributes": {}, "status": {"code": "ERROR", "description": None}}
    child = span("c", parent="p", code="OK")
    assert top_level([parent, child]) == [parent]
    o = obs([call("cut", usage=None, text=(), finish=())], [parent, {**child, "events": [{"name": "exception"}],
            "status": {"code": "ERROR"}}], outcome="exception", exception="APIConnectionError")
    assert compare(o) == []


def test_failed_call_without_error_status_or_exception_event_is_medium():
    o = obs([call("error_event", usage=None, text=(), finish=())], [span(code="ERROR")],
            outcome="exception", exception="APIError")
    [m] = compare(o)
    assert (m.check, m.severity, m.trace) == ("call_status", Severity.MEDIUM, "ERROR, no exception event")


def test_duplicate_span_is_call_count_high():
    o = obs([call()], [span("a"), span("b", start=2)])
    assert ("call_count", Severity.HIGH) in checks(o)


def test_missing_span_is_span_closed_high():
    o = obs([call(), call(rid="chatcmpl-2")], [span()])
    ms = [m for m in compare(o) if m.check == "span_closed"]
    assert len(ms) == 1 and ms[0].field == "call 2 span" and ms[0].severity is Severity.HIGH


def test_tokens_sum_off_is_high_per_span_off_with_same_sum_is_medium():
    o = obs([call()], [span(attrs={"neatlogs.llm.token_count.completion": 8})])
    assert checks(o) == [("tokens", Severity.HIGH)]
    swapped = obs([call(), call(rid="chatcmpl-2")], [
        span("a", attrs={"neatlogs.llm.token_count.prompt": 7, "neatlogs.llm.token_count.completion": 11}),
        span("b", start=2, attrs={"neatlogs.llm.response_id": "chatcmpl-2"}),
    ])
    assert checks(swapped) == [("tokens", Severity.MEDIUM)]


def test_tokens_not_compared_when_the_fake_sent_no_usage():
    o = obs([call(usage=None)], [span(attrs={"neatlogs.llm.token_count.prompt": None,
                                             "neatlogs.llm.token_count.completion": None})])
    assert compare(o) == []


def test_missing_text_refusal_and_wrong_tool_args_are_medium():
    o = obs([call(text=("I can't help with that.",))], [span(attrs={"neatlogs.llm.output_messages.0.content": None})])
    assert checks(o) == [("output", Severity.MEDIUM)]
    tools = call(text=(), finish=("tool_calls",), tools=[("get_weather", '{"city":"Lagos"}')])
    good = span(attrs={"neatlogs.llm.finish_reason": "tool_calls", "neatlogs.llm.tool_calls.0.name": "get_weather",
                       "neatlogs.llm.tool_calls.0.arguments": '{"city": "Lagos"}'})
    assert compare(obs([tools], [good])) == []
    bad = span(attrs={**good["attributes"], "neatlogs.llm.tool_calls.0.arguments": '{"city":"Lago'})
    assert checks(obs([tools], [bad])) == [("output", Severity.MEDIUM)]


def test_finish_missing_or_failed_not_visible_is_medium():
    o = obs([call()], [span(attrs={"neatlogs.llm.finish_reason": None})])
    assert checks(o) == [("finish", Severity.MEDIUM)]
    inc = call("incomplete", finish=("incomplete",))
    assert checks(obs([inc], [span(attrs={"neatlogs.llm.finish_reason": None})])) == [("finish", Severity.MEDIUM)]
    assert compare(obs([inc], [span(attrs={"neatlogs.llm.finish_reason": "max_tokens"})])) == []


def test_finish_compared_with_synonyms():
    o = obs([call(finish=("end_turn",))], [span()])
    assert compare(o) == []


def test_early_closed_stream_skips_output_tokens_and_finish():
    o = obs([call()], [span(attrs={"neatlogs.llm.token_count.prompt": None, "neatlogs.llm.finish_reason": None,
                                   "neatlogs.llm.output_messages.0.content": "h"})], result={"chunks_read": 1})
    assert compare(o) == []


def test_library_added_include_usage_is_a_low_note_and_tokens_use_what_was_sent():
    c = call(include_usage=True)
    o = obs([c], [span()], expected={"tokens": [None]})
    [m] = compare(o)
    assert (m.check, m.kind, m.severity) == ("request_changed", "note", Severity.LOW)
    assert leads(compare(o)) == []


def test_match_by_response_id_then_order():
    a = ADAPTERS["neatlogs"]
    s1 = span("a", attrs={"neatlogs.llm.response_id": "chatcmpl-2"})
    s2 = span("b", attrs={"neatlogs.llm.response_id": None})
    llm = [(s, facts(a, s)) for s in (s1, s2)]
    assert match_calls([call(rid="chatcmpl-1"), call(rid="chatcmpl-2")], llm) == [1, 0]


# Real span JSON from the sweeps.


def fixture(name):
    return Observation.from_dict(json.loads((FIX / f"{name}.json").read_text())["observation"])


@pytest.mark.parametrize("name", ["neatlogs-oa-chat-tools", "openinference-oa-chat-tools", "openllmetry-oa-chat-tools",
                                  "openinference-oa-chat-stream-cut", "neatlogs-oa-chat-stream-cut",
                                  "openinference-an-stream-tools"])
def test_real_clean_fixtures_have_no_leads(name):
    assert leads(compare(fixture(name))) == []


def test_real_openllmetry_stream_cut_shows_ok():
    got = {(m.check, m.severity) for m in compare(fixture("openllmetry-oa-chat-stream-cut"))}
    assert got == {("run_status", Severity.HIGH), ("call_status", Severity.MEDIUM)}


def test_real_openllmetry_anthropic_stream_tokens_off():
    [m] = compare(fixture("openllmetry-an-stream-helper"))
    assert (m.check, m.severity, m.truth, m.trace) == ("tokens", Severity.HIGH, {"input": 5, "output": 3},
                                                       {"input": 5, "output": 4})


def test_real_refusal_missing_in_neatlogs_and_openinference():
    for lib in ("neatlogs", "openinference"):
        assert [m.check for m in compare(fixture(f"{lib}-oa-chat-refusal"))] == ["output"]
    assert compare(fixture("openllmetry-oa-chat-refusal")) == []


def test_real_neatlogs_streamed_chat_note_but_no_lead():
    ms = compare(fixture("neatlogs-oa-chat-stream-cut"))
    assert [(m.check, m.kind) for m in ms] == [("request_changed", "note")]



# Framework runs: root span, tool spans, errors that come from the framework.


def tool_span(sid, name="get_weather", parent="root", code="UNSET", events=()):
    return {"name": name, "span_id": sid, "parent_id": parent, "start_ns": 5,
            "status": {"code": code, "description": None},
            "attributes": {"neatlogs.span.kind": "tool", "neatlogs.tool.name": name},
            "events": [{"name": e, "attributes": {}} for e in events]}


def root(code="OK"):
    return {"name": "Agent workflow", "span_id": "root", "parent_id": None, "start_ns": 0,
            "status": {"code": code, "description": None}, "attributes": {}, "events": []}


def fw_obs(spans, tool_runs, **kw):
    o = obs([call()], spans, **kw)
    return Observation(truth={**o.truth, "tool_runs": tool_runs}, trace=o.trace)


def test_top_level_prefers_the_trace_root_over_orphans():
    orphan = span("o", parent="never-exported", code="ERROR")
    assert top_level([root(), orphan]) == [root()]
    assert top_level([orphan]) == [orphan]


def test_tool_run_without_span_and_raised_tool_shown_ok_are_medium():
    runs = [{"name": "get_weather", "outcome": "ok"}, {"name": "get_weather", "outcome": "raised"}]
    o = fw_obs([root(), span(parent="root"), tool_span("t1")], runs)
    assert [(m.check, m.field, m.severity) for m in compare(o)] == [
        ("tools", "tool run 2 (get_weather) span", Severity.MEDIUM)]
    o = fw_obs([root(), span(parent="root"), tool_span("t1"), tool_span("t2", code="OK")], runs)
    assert [(m.check, m.field) for m in compare(o)] == [("tools", "tool run 2 (get_weather) status")]
    o = fw_obs([root(), span(parent="root"), tool_span("t1"), tool_span("t2", events=("exception",))], runs)
    assert compare(o) == []


def test_extra_tool_span_is_low():
    o = fw_obs([root(), span(parent="root"), tool_span("t1"), tool_span("t2")], [{"name": "get_weather", "outcome": "ok"}])
    assert checks(o) == [("tools", Severity.LOW)]


def test_framework_error_recorded_nowhere_is_medium_and_root_ok_is_high():
    o = fw_obs([root(), span(parent="root")], [], outcome="exception", exception="ModelBehaviorError")
    assert checks(o) == [("error_recorded", Severity.MEDIUM), ("run_status", Severity.HIGH)]
    turn = {**span("turn", parent="root"), "attributes": {}, "status": {"code": "ERROR", "description": "Tool not found"}}
    o = fw_obs([root(), turn, span(parent="turn")], [], outcome="exception", exception="ModelBehaviorError")
    assert checks(o) == [("run_status", Severity.HIGH)]


def test_app_asked_for_stream_usage_is_not_a_request_change():
    c = call("cut", usage=None, text=(), finish=(), include_usage=True)
    exp = {"tokens": [None], "include_usage": [True]}
    o = obs([c], [span(code="ERROR", events=("exception",))], outcome="exception", exception="X", expected=exp)
    assert compare(o) == []
    o = obs([c], [span(code="ERROR", events=("exception",))], outcome="exception", exception="X",
            expected={**exp, "include_usage": [False]})
    assert [(m.check, m.kind) for m in compare(o)] == [("request_changed", "note")]


def test_real_agents_sdk_unknown_tool_root_ok():
    # OpenInference: the root stays OK; the error is only on the turn span's status.
    ms = compare(fixture("openinference-ag-bad-tool"))
    assert [(m.check, m.severity) for m in ms] == [("run_status", Severity.HIGH)]
    # OpenLLMetry: the root stays OK and no span records the error at all.
    got = {m.check for m in compare(fixture("openllmetry-ag-bad-tool"))}
    assert {"run_status", "error_recorded"} <= got


def test_real_openllmetry_agents_sdk_doubles_llm_spans_only_when_not_streamed():
    ms = compare(fixture("openllmetry-ag-run"))
    [m] = [m for m in ms if m.check == "call_count"]
    assert (m.truth, m.trace, m.severity) == ("2 (provider requests)", 4, Severity.HIGH)
    assert [m.check for m in compare(fixture("openllmetry-ag-streamed"))] == []


@pytest.mark.parametrize("name", ["openllmetry-lg-agent", "openinference-lg-agent", "neatlogs-lg-tool-raises"])
def test_real_langgraph_spans_counted_right(name):
    # LangGraph task, tool and workflow spans are not LLM calls; tool spans pair with tool runs.
    assert [m.check for m in leads(compare(fixture(name))) if m.check in ("call_count", "tools", "span_closed")] == []
