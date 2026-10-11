"""Checker rules, verdict, grouping, repro text and dedupe matching. All pure, over recorded data."""

import copy
import json
from pathlib import Path

import pytest

from trueup import dedupe
from trueup.check import scenario_for_run
from trueup.cli import EXIT_ERROR, main
from trueup.core import checker, group, repro
from trueup.core.checker import COULD_NOT_CHECK, DISPUTED, FAIL, PASS

LEAD = {"scenario": "oa-resp-plain", "library": "neatlogs", "check": "finish", "field": "call 1 finish",
        "truth": ["completed"], "trace": None, "severity": "medium"}
SIG = checker.signature(LEAD)


def test_temporary_comparison_scenario_is_recovered_from_retained_proposal(tmp_path):
    data = {"id": "p-temp", "provider": "openai", "api": "responses", "framework": "none",
            "does": "streams", "app": "resp_stream", "model": "resp-failed",
            "expected": {"calls": 1, "outcome": "exception", "exception": "RuntimeError", "fake": ["failed"]}}
    path = tmp_path / ".trueup" / "v1v2" / "v1" / "proposed" / "neatlogs" / "p-temp.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data))
    got = scenario_for_run(tmp_path, "p-temp", {"truth": {"expected": data["expected"]}})
    assert got.id == "p-temp" and got.app == "resp_stream"


def evidence(**over):
    ev = {
        "lead": dict(LEAD),
        "observation": {"truth": {"fake_log": [{"response_id": "resp-1", "usage_sent": True,
                                                "usage": {"input_tokens": 11, "output_tokens": 7},
                                                "scenario": "resp-plain"}],
                                  "expected_mismatch": [], "app": {"outcome": "ok"}}},
        "reruns": [{"status": "ran", "leads": [SIG], "versions": {"neatlogs": "1.0"}, "seconds": 3.0,
                    "framework": "none", "setup": "neatlogs.init"}] * 2,
        "latest": {"installed": {"neatlogs": "1.0"}, "pypi": {"neatlogs": "1.0"}},
        "main": {"status": "ran", "leads": [SIG], "commit": "abcdef1234567"},
        "harness": {"env": {"NEATLOGS_DISABLE_EXPORT": "true", "OTEL_TRACES_EXPORTER": "none"}},
        "others": {"openllmetry": {"status": "ran", "leads": []}},
        "repro": {"status": "ran", "lines": 30, "leads": [SIG], "path": "r.py"},
    }
    ev.update(over)
    return ev


def test_all_rules_pass_is_a_finding():
    results = checker.run_rules(evidence())
    assert [r.status for r in results] == [PASS] * 7
    assert checker.verdict(results) == (checker.FINDING, None)


def test_fresh_process_needs_two_identical_reruns():
    other = [*SIG[:3], ["stop"]]
    ev = evidence(reruns=[evidence()["reruns"][0], {"status": "ran", "leads": [other], "seconds": 1}])
    r = checker.fresh_process(ev)
    assert r.status == FAIL and "rerun 2" in r.reason
    assert checker.fresh_process(evidence(reruns=[])).status == COULD_NOT_CHECK


def test_recommended_setup_needs_the_framework_installed():
    ev = evidence(reruns=[{"status": "ran", "framework": "langgraph", "versions": {"langchain-core": "1"}}] * 2)
    r = checker.recommended_setup(ev)
    assert r.status == FAIL and "langgraph" in r.reason


def test_latest_and_main():
    assert checker.latest_and_main(evidence(latest={"installed": {"neatlogs": "0.9"},
                                                    "pypi": {"neatlogs": "1.0"}})).status == FAIL
    fixed = checker.latest_and_main(evidence(main={"status": "ran", "leads": [], "commit": "abc"}))
    assert fixed.status == FAIL and "fixed" in fixed.reason
    cnc = checker.latest_and_main(evidence(main={"status": "could_not_install", "reason": "build failed"}))
    assert cnc.status == COULD_NOT_CHECK and "build failed" in cnc.reason


def test_main_not_checked_with_reason_and_rest_passing_is_a_finding():
    results = checker.run_rules(evidence(main={"status": "could_not_install", "reason": "build failed"}))
    status, by = checker.verdict(results)
    assert status == checker.FINDING and by.rule == "latest_and_main"
    results = checker.run_rules(evidence(main={"status": "could_not_install", "reason": "x"}, repro={}))
    assert checker.verdict(results)[0] == checker.LEAD


def test_fake_truthful():
    ev = evidence()
    ev["observation"]["truth"]["fake_log"] = [{"response_id": "a"}, {"response_id": "a"}]
    assert checker.fake_truthful(ev).status == FAIL
    tok = evidence(lead={**LEAD, "check": "tokens", "field": "call 1 tokens"})
    assert checker.fake_truthful(tok).status == PASS
    tok["observation"]["truth"]["fake_log"][0]["usage_sent"] = False
    r = checker.fake_truthful(tok)
    assert r.status == FAIL and "no usage" in r.reason


def test_harness_sane():
    ev = evidence()
    ev["observation"] = copy.deepcopy(ev["observation"])
    ev["observation"]["truth"]["app"] = {"outcome": "exception", "message": "Event loop is closed"}
    assert checker.harness_sane(ev).status == FAIL
    dead = evidence(harness={"env": {"NEATLOGS_DISABLE_EXPORT": "true", "OTEL_TRACES_EXPORTER": "none",
                                      "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:1"}})
    assert checker.harness_sane(dead).status == FAIL
    slow = evidence(reruns=[{**evidence()["reruns"][0], "seconds": 200}] * 2)
    assert checker.harness_sane(slow).status == FAIL


def test_reference_other_library_semconv_or_disputed():
    assert "openllmetry" in checker.reference(evidence()).reason
    agree = {"openllmetry": {"status": "ran", "leads": [SIG]}}
    assert checker.reference(evidence(others=agree)).reason.startswith("OTel GenAI")
    exc = {**LEAD, "check": "call_status", "field": "call 1 span status", "trace": "ERROR, no exception event"}
    r = checker.reference(evidence(lead=exc, others={"openllmetry": {"status": "ran",
                                                                     "leads": [checker.signature(exc)]}}))
    assert r.status == DISPUTED
    sig = checker.signature(exc)
    ev = evidence(lead=exc, others={"x": {"status": "ran", "leads": [sig]}},
                  reruns=[{**evidence()["reruns"][0], "leads": [sig]}] * 2,
                  main={"status": "ran", "leads": [sig], "commit": "abc"},
                  repro={"status": "ran", "lines": 30, "leads": [sig]})
    assert checker.verdict(checker.run_rules(ev))[0] == checker.DISPUTED_SEMANTICS


def test_refusal_has_no_semconv_reference():
    ev = evidence(lead={**LEAD, "check": "output", "field": "call 1 output text", "truth": "no"})
    ev["observation"]["truth"]["fake_log"][0]["scenario"] = "chat-refusal"
    assert checker.semconv_reference(ev["lead"], ev["observation"]["truth"]["fake_log"]) is None


def test_repro_rule():
    assert checker.repro(evidence(repro={"status": "ran", "lines": 45, "leads": [SIG]})).status == FAIL
    assert checker.repro(evidence(repro={"status": "ran", "lines": 30, "leads": []})).status == FAIL
    assert checker.repro(evidence(repro={"status": "not_run", "reason": "exit 1"})).status == COULD_NOT_CHECK


def test_withdrawn_names_the_first_failing_rule():
    status, by = checker.verdict(checker.run_rules(evidence(reruns=[])))
    assert status == checker.LEAD and by.rule == "fresh_process"
    status, by = checker.verdict(checker.run_rules(evidence(repro={"status": "ran", "lines": 50, "leads": [SIG]})))
    assert status == checker.WITHDRAWN and by.rule == "repro"


def test_generated_repro_is_short_and_names_the_scenario():
    text = repro.generate("neatlogs", "oa-resp-plain", "One Responses call, reads output_text.")
    assert repro.line_count(text) < checker.REPRO_MAX_LINES
    assert 'get("oa-resp-plain")' in text and 'SETUPS["neatlogs"]' in text
    compile(text, "repro.py", "exec")


def _item(sid, field="call 1 finish", framework="none", app="resp_create", trace=None, check="finish"):
    return {"lead": {**LEAD, "scenario": sid, "field": field, "trace": trace, "check": check},
            "scenario": {"framework": framework, "provider": "openai", "api": "responses", "app": app},
            "rules": [{"rule": "fresh_process", "status": PASS, "reason": "ok"}], "decided_by": None}


def test_group_by_library_check_and_code_path():
    items = [_item("oa-resp-plain"), _item("oa-resp-tool"), _item("oa-resp-plain", field="call 2 finish"),
             _item("oa-resp-stream", app="resp_stream"),
             _item("ag-run", framework="openai-agents", app="ag_run"),
             _item("oa-resp-x", check="call_status", field="call 1 span status", trace="OK"),
             _item("oa-resp-y", check="call_status", field="call 1 span status", trace="ERROR, no exception event")]
    fs = group.group(items)
    assert len(fs) == 5
    create = next(f for f in fs if f.details["code_path"] == "openai responses create" and f.details["check"] == "finish")
    assert create.details["scenarios"] == ["oa-resp-plain", "oa-resp-tool"]
    assert len(create.details["leads"]) == 3
    assert create.title == "neatlogs, openai responses create: finish not recorded"


def _finding(sid="oa-resp-plain", path_app="resp_create"):
    return group.group([_item(sid, app=path_app)])[0]


def test_dedupe_queries_and_matches():
    f = _finding()
    assert dedupe.queries(f) == ["responses finish reason", "finish reason"]
    items = [{"title": "Responses API spans miss finish_reason", "url": "u1"},
             {"title": "finish reason for anthropic", "url": "u2"},
             {"title": "Responses API support", "url": "u3"}]
    assert [m["url"] for m in dedupe.matches(f, items)] == ["u1"]


def test_dedupe_records_searches_and_never_writes():
    calls = []

    def fake_search(args):
        calls.append(args)
        assert args[1:3] == ["--repo", "neatlogs/neatlogs"] and "--include-prs" in args
        return json.dumps([{"number": 7, "title": "responses: finish_reason missing", "url": "https://x/7",
                            "state": "open", "isPullRequest": False, "createdAt": "2026-01-01"}])

    f = _finding()
    out = dedupe.dedupe("neatlogs", [f], fake_search)[f.id]
    assert out["status"] == "already known" and out["links"] == ["https://x/7"]
    assert {s["query"] for s in out["searches"]} == {"responses finish reason", "finish reason"}
    assert all(s["date"] and s["states"] == "all" for s in out["searches"])
    assert out["integration_titles"]["titles"] == ["#7 responses: finish_reason missing (open)"]
    assert len(calls) == 3


def test_dedupe_search_error_is_recorded_not_raised():
    def broken(args):
        raise RuntimeError("rate limited")

    f = _finding()
    out = dedupe.dedupe("neatlogs", [f], broken)[f.id]
    assert out["status"] == "not found" and out["errors"]


def test_check_without_a_sweep_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["check", "latest", "--library", "neatlogs"]) == EXIT_ERROR
    assert "no sweep" in capsys.readouterr().err


@pytest.mark.parametrize("lib", ["neatlogs", "openinference", "openllmetry"])
def test_dedupe_has_a_repo_per_library(lib):
    assert dedupe.REPOS[lib].count("/") == 1


def test_reviewed_match_that_does_not_cover_is_related_only(monkeypatch):
    f = _finding()
    monkeypatch.setitem(dedupe.REVIEWED_NOT_COVERING, (f.id, "https://x/7"), "different case")
    hit = json.dumps([{"number": 7, "title": "responses: finish_reason missing", "url": "https://x/7",
                       "state": "open", "isPullRequest": True, "createdAt": "2026-01-01"}])
    out = dedupe.dedupe("neatlogs", [f], lambda args: hit)[f.id]
    assert out["status"] == "not found" and out["related"][0]["why_not"] == "different case"


def test_token_findings_ignore_reasoning_token_titles():
    f = group.group([_item("an-stream-helper", check="tokens", field="call 1 tokens",
                           trace={"input": 5, "output": 4})])[0]
    f.details["code_path"] = "anthropic messages stream"
    items = [{"title": "feat(anthropic): emit reasoning tokens usage", "url": "u1"},
             {"title": "anthropic stream output tokens counted wrong", "url": "u2"}]
    assert [m["url"] for m in dedupe.matches(f, items)] == ["u2"]
