"""trueup audit, offline: the child run is replaced by a stub."""

import json
from pathlib import Path

from trueup.audit import DISCOVER, audit, load_mine
from trueup.cli import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK, main
from trueup.fake import FakeProvider
from trueup.fake.server import SCENARIOS_BY_ROUTE
from trueup.runner import NOT_RUN, RAN
from trueup.sweep import exit_code

CHAT = "/v1/chat/completions"


def obs(label, path=CHAT, span_code="OK", calls=1):
    fake_log = [{"path": path, "response_id": None, "outcome": "complete", "usage": None, "usage_sent": False,
                 "text": [], "finish": [], "tool_calls": [], "include_usage": False}] * calls
    spans = [{"name": "chat", "span_id": "s", "parent_id": None, "start_ns": 1, "status": {"code": span_code},
              "attributes": {"openinference.span.kind": "LLM"}, "events": []}]
    return {"scenario": label, "library": "openinference", "status": RAN, "reason": None, "seconds": 0.1,
            "observation": {"truth": {"calls": calls, "outcome": "ok", "app": {"outcome": "ok"},
                                      "fake_log": fake_log},
                            "trace": {"library": "openinference", "spans": spans}}}


def stub(seen, bad=None, calls=1):
    def run(py, lib, script, label, overrides):
        seen.append((label, overrides))
        return obs(label, span_code="ERROR" if label == bad else "OK", calls=0 if calls == 0 else 1)
    return run


def go(tmp_path, run, script=None, run_id=None):
    if script is None:
        script = tmp_path / "agent.py"
        script.write_text("def main(): pass\n")
    return audit(tmp_path, "openinference", script, ensure=lambda r, l: Path("/py"), run=run, out=lambda s: None,
                 run_id=run_id)


def test_runs_every_scenario_of_the_routes_main_calls(tmp_path):
    seen = []
    run_dir, results = go(tmp_path, stub(seen))
    assert seen[0] == (DISCOVER, {})
    assert seen[1:] == [(s, {CHAT: s}) for s in SCENARIOS_BY_ROUTE[CHAT]]
    assert exit_code(results) == EXIT_OK
    assert json.loads((run_dir / "leads.json").read_text())["counts"]["leads"] == 0
    assert "-audit-openinference" in run_dir.name


def test_a_lead_exits_1(tmp_path):
    _, results = go(tmp_path, stub([], bad="chat-tools"))
    assert exit_code(results) == EXIT_MISMATCH


def test_neatlogs_audit_emits_one_redacted_marker_per_mismatch(tmp_path, monkeypatch):
    marks = []
    monkeypatch.setattr("trueup.audit.tracing.mark", lambda name, **attrs: marks.append((name, attrs)))
    script = tmp_path / "agent.py"
    script.write_text("def main(): pass\n")
    audit(tmp_path, "openinference", script, ensure=lambda *_: Path("/py"),
          run=stub([], bad="chat-tools"), out=lambda _: None, neatlogs=True)
    assert marks
    assert all(name == "Trueup mismatch" for name, _ in marks)
    assert all(set(attrs) == {"scenario", "check", "field", "severity"} for _, attrs in marks)


def test_no_provider_call_could_not_run(tmp_path):
    _, results = go(tmp_path, stub([], calls=0))
    assert [r["status"] for r in results] == [NOT_RUN] and "no provider call" in results[0]["reason"]
    assert exit_code(results) == EXIT_ERROR


def test_missing_script_could_not_run(tmp_path):
    _, results = go(tmp_path, stub([]), script=tmp_path / "nope.txt")
    assert exit_code(results) == EXIT_ERROR and "no such file" in results[0]["reason"]


def test_audit_resumes_discovery_and_scenarios(tmp_path):
    seen = []
    go(tmp_path, stub(seen), run_id="resume-audit")
    first_count = len(seen)
    go(tmp_path, stub(seen), run_id="resume-audit")
    assert len(seen) == first_count


def test_record_audit_runs_once_and_resumes(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("def main(): pass\n")
    seen = []

    def real_run(_python, _library, _script, provider, base_url, recording):
        seen.append((provider, base_url, recording.name))
        return obs("record")

    kwargs = {"ensure": lambda *_: Path("/py"), "out": lambda _: None, "run_id": "real-1",
              "record_provider": "openai", "upstream": "https://api.openai.com", "record_run": real_run}
    audit(tmp_path, "openinference", script, **kwargs)
    audit(tmp_path, "openinference", script, **kwargs)
    assert len(seen) == 1
    assert seen[0][0] == "openai" and seen[0][2] == "recording.jsonl"


def test_cli_audit_needs_a_library(capsys):
    try:
        main(["audit", "agent.py"])
    except SystemExit as e:
        assert e.code == 2
    assert "--library" in capsys.readouterr().err


def test_fake_override_picks_scenario_whatever_the_model():
    import httpx

    with FakeProvider({CHAT: "chat-500"}) as fake:
        r = httpx.post(f"{fake.openai_base_url}/chat/completions", json={"model": "gpt-4o", "messages": []})
        plain = httpx.post(f"{fake.base_url}/v1/messages", json={"model": "claude", "max_tokens": 5, "messages": []})
    assert r.status_code == 500 and plain.status_code == 200
    assert [e["scenario"] for e in fake.log.entries()] == ["chat-500", "claude"]


def test_custom_cases_run_only_reviewed_case_data(tmp_path):
    case_dir = tmp_path / ".trueup" / "cases"
    case_dir.mkdir(parents=True)
    (case_dir / "failure.json").write_text(json.dumps({
        "id": "my-chat-failure", "route": CHAT, "scenario": "chat-500"}))
    seen = []
    script = tmp_path / "agent.py"
    script.write_text("def main(): pass\n")
    _, results = audit(tmp_path, "openinference", script, ensure=lambda *_: Path("/py"), run=stub(seen),
                       out=lambda _: None, cases="mine")
    assert seen == [(DISCOVER, {}), ("my-chat-failure", {CHAT: "chat-500"})]
    assert [r["scenario"] for r in results] == ["my-chat-failure"]


def test_custom_cases_reject_wrong_route_behavior(tmp_path):
    case_dir = tmp_path / ".trueup" / "cases"
    case_dir.mkdir(parents=True)
    (case_dir / "bad.json").write_text(json.dumps({"id": "bad", "route": CHAT, "scenario": "claude"}))
    try:
        load_mine(tmp_path)
    except ValueError as error:
        assert "not valid" in str(error)
    else:
        raise AssertionError("invalid custom case accepted")
