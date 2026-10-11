"""Offline tests for the fixer, the verifier rules and the upstream drafts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trueup import tracing
from trueup.cli import build_parser
from trueup.core.repro import line_count
from trueup.fix import find_finding
from trueup.fixer import locate as loc
from trueup.fixer import patch as pt
from trueup.fixer import targets as tg
from trueup.fixer import verify as vf
from trueup import upstream as up

TARGET = tg.Target(library="lib", code_path="x", packages=(tg.Package("pkg", "pkg"),), seeds=("wrap",),
                   reference_seeds=("KEY",))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg" / "lib").mkdir(parents=True)
    (tmp_path / "pkg" / "tests").mkdir()
    (tmp_path / "pkg" / "lib" / "w.py").write_text(
        "KEY = 1\n\n\nclass P:\n    def wrap(self, x):\n        return x\n\n    def use(self):\n"
        "        return self.wrap(1)\n\n\ndef top():\n    return P().wrap(2)\n")
    (tmp_path / "build" / "lib").mkdir(parents=True)
    (tmp_path / "build" / "lib" / "w.py").write_text("def wrap():\n    pass\n")
    return tmp_path


def draft(**kw):
    d = {"edits": [{"file": "pkg/lib/w.py", "old": "        return x\n", "new": "        return x + 1\n"}],
         "test": {"file": "pkg/tests/test_trueup_w.py", "content": "def test_x():\n    assert True\n"}}
    d.update(kw)
    return d


def test_check_draft_applies_and_returns_writes(repo: Path) -> None:
    writes = pt.check_draft(draft(), repo, TARGET)
    assert writes == [{"file": "pkg/lib/w.py", "content": (repo / "pkg/lib/w.py").read_text().replace(
        "return x\n", "return x + 1\n")}]


@pytest.mark.parametrize("edits, reason", [
    ([{"file": "other/w.py", "old": "a", "new": "b"}], "outside"),
    ([{"file": "build/lib/w.py", "old": "pass", "new": "x"}], "outside"),
    ([{"file": "pkg/tests/test_a.py", "old": "a", "new": "b"}], "outside"),
    ([{"file": "pkg/lib/w.py", "old": "return y\n", "new": ""}], "found 0 times"),
    ([{"file": "pkg/lib/w.py", "old": "wrap(", "new": "w("}], "found 3 times"),
    ([{"file": "pkg/lib/w.py", "old": "        return x\n", "new": "        return (\n"}], "does not compile"),
    ([], "non-empty"),
])
def test_check_draft_refuses(repo: Path, edits: list, reason: str) -> None:
    with pytest.raises(pt.PatchError, match=reason):
        pt.check_draft(draft(edits=edits), repo, TARGET)


def test_check_draft_shows_the_nearest_real_lines(repo: Path) -> None:
    with pytest.raises(pt.PatchError, match="really has, from line 5"):
        pt.check_draft(draft(edits=[{"file": "pkg/lib/w.py", "old": "    def wrap(self, y):\n", "new": ""}]),
                       repo, TARGET)


@pytest.mark.parametrize("test_file", ["pkg/lib/test_trueup_w.py", "pkg/tests/test_w.py", "pkg/tests/x.txt"])
def test_check_draft_test_file_must_be_new_trueup_test_in_tests(repo: Path, test_file: str) -> None:
    with pytest.raises(pt.PatchError, match="test file"):
        pt.check_draft(draft(test={"file": test_file, "content": "x = 1\n"}), repo, TARGET)


def test_locate_finds_definitions_callers_and_reference_skipping_build(repo: Path) -> None:
    found = loc.locate_symbols(repo, TARGET)
    assert [(d["file"], d["qualname"]) for d in found["definitions"]] == [("pkg/lib/w.py", "P.wrap")]
    assert sorted(c["in"] for c in found["callers"]) == ["P.use", "top"]
    assert all(not r["file"].startswith("build/") for r in found["callers"] + found["reference"])


def test_source_excerpt_is_verbatim(repo: Path) -> None:
    found = loc.locate_symbols(repo, TARGET)
    text = loc.source_excerpts(repo, found, limit=10)  # forces the excerpt path
    assert "    def wrap(self, x):\n        return x" in text
    assert "5: " not in text  # no line-number prefixes the model could copy into an edit


def test_probe_graph_records_why_it_was_not_used(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr(loc.shutil, "which", lambda name: "/bin/" + name)

    def run(cmd, cwd, timeout):
        missing = cmd[1] == "graph"
        return subprocess.CompletedProcess(cmd, 1 if missing else 0, "" if missing else "help",
                                           "the entire-graph plugin is not installed" if missing else "")

    rec = loc.probe_graph(repo, ("wrap",), run)
    assert rec["used"] is False and "not installed" in rec["reason"] and len(rec["commands"]) == 3


JUNIT = """<?xml version="1.0"?><testsuites><testsuite name="pytest">
<testcase classname="tests.test_a" name="test_ok"/><testcase classname="tests.test_a" name="test_bad"><failure/></testcase>
<testcase classname="tests.test_b" name="test_skip"><skipped/></testcase>
<testcase classname="" name="tests.test_c"><error/></testcase></testsuite></testsuites>"""


def test_parse_junit(tmp_path: Path) -> None:
    (tmp_path / "j.xml").write_text(JUNIT)
    r = vf.parse_junit(tmp_path / "j.xml")
    assert (r["total"], r["passed"], r["failed"], r["errors"], r["skipped"]) == (4, 1, 1, 1, 1)
    assert r["failing"] == ["::tests.test_c", "tests.test_a::test_bad"]


def suite(failing: list[str], total: int = 10, exit: int = 1, passed: int = 9) -> dict:
    return {"failing": failing, "total": total, "exit": exit, "passed": passed, "tail": "", "tests": []}


def test_suite_verdict() -> None:
    before = suite(["a::old"])
    assert vf.suite_verdict(before, suite(["a::old"], total=11)) == (True, "same 1 failure(s) as before the patch")
    assert vf.suite_verdict(before, suite([], total=11))[0]
    ok, why = vf.suite_verdict(before, suite(["a::old", "a::new"], total=11))
    assert not ok and "a::new" in why
    # The new test passed alone but fails inside the full suite: that is a failure too.
    assert not vf.suite_verdict(before, suite(["a::old", "test_trueup_x::test_y"], total=11))[0]
    assert not vf.suite_verdict(before, suite([], total=5))[0]  # fewer tests ran
    assert not vf.suite_verdict(before, {"exit": 2, "tail": "boom"})[0]


def test_baseline_must_really_run() -> None:
    assert vf.baseline_usable(suite([], exit=0))[0]
    assert not vf.baseline_usable(suite(["x"], total=1, exit=2, passed=0))[0]  # collection interrupted
    assert not vf.baseline_usable({"exit": -1, "tail": "timed out"})[0]


def test_new_test_verdict_and_weak_tests() -> None:
    before = {"total": 2, "failing": ["m::test_a"], "tests": ["m::test_a", "m::test_b"], "exit": 1, "tail": ""}
    ok, why = vf.new_test_verdict(before, {"total": 2, "failing": [], "exit": 0, "tail": ""})
    assert ok and "test_b" in why and "do not show the bug" in why
    assert not vf.new_test_verdict({**before, "failing": []}, {"total": 2, "failing": [], "exit": 0, "tail": ""})[0]
    assert not vf.new_test_verdict(before, {"total": 2, "failing": ["m::test_a"], "exit": 1, "tail": ""})[0]
    assert not vf.new_test_verdict({"total": 0, "exit": 4, "tail": ""}, {"total": 1, "failing": []})[0]


FINDING = {"id": "f", "details": {"check": "run_status", "field": "status", "scenarios": ["ag-a", "ag-b"]}}


def lead(check: str = "run_status", field: str = "status", truth: str = "ERROR", trace: str = "OK") -> dict:
    return {"check": check, "field": field, "truth": truth, "trace": trace, "severity": "high"}


def test_scenario_verdict_new_mismatches_and_table() -> None:
    before = {"leads": {"ag-a": [lead()], "ag-b": [lead(), lead("tokens", "t", 1, 2)], "ag-c": []}, "not_run": {}}
    after = {"leads": {"ag-a": [], "ag-b": [lead("tokens", "t", 1, 2)], "ag-c": [lead(truth="OK", trace="ERROR")]},
             "not_run": {}, "spans": {}}
    assert vf.scenario_verdict(after, FINDING)[0]
    new = vf.new_mismatches(before, after)
    assert [(m["scenario"], m["trace"]) for m in new] == [("ag-c", "ERROR")]
    still = {"leads": {"ag-a": [lead()], "ag-b": []}, "not_run": {}, "spans": {"ag-a": [["root", "OK", "", None]]}}
    ok, why = vf.scenario_verdict(still, FINDING)
    assert not ok and "ag-a: truth ERROR, trace OK" in why and "root" in why
    assert not vf.scenario_verdict({"leads": {"ag-a": []}, "not_run": {}}, FINDING)[0]
    rows = vf.before_after(FINDING, before, after)
    assert rows[0] == {"scenario": "ag-a", "field": "status", "truth": "ERROR", "before": "OK",
                       "after": "matches truth"}
    assert "| before | 3 | 0 | 3 |" in vf.table_md(rows, vf.totals(before), vf.totals(after))


def test_test_requirements_reads_groups_and_files(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "pyproject.toml").write_text('[dependency-groups]\ntest = ["pytest>=8", {include-group = "x"}]\n')
    (tmp_path / "p" / "req.txt").write_text("respx  # mock\n-e ../x\n\nvcrpy\n")
    pkg = tg.Package("p", "p", test_deps=("group:test", "file:req.txt", "extra"))
    assert vf.test_requirements(tmp_path, pkg) == ["pytest>=8", "respx", "vcrpy", "extra"]


def test_test_env_drops_every_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("TRUEUP_MODEL_KEY", "NEATLOGS_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "VIRTUAL_ENV"):
        monkeypatch.setenv(k, "v")
    env = vf.test_env()
    assert not {"TRUEUP_MODEL_KEY", "NEATLOGS_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "VIRTUAL_ENV"} & set(env)


def write_findings(root: Path, run: str, scenarios: list[str]) -> None:
    d = root / ".trueup" / "runs" / run
    d.mkdir(parents=True)
    leads = [{**lead(), "scenario": s} for s in scenarios]
    (d / "findings.json").write_text(json.dumps({"findings": [
        {"id": "f", "library": "neatlogs", "details": {**FINDING["details"], "scenarios": scenarios, "leads": leads}}]}))


def test_find_finding_merges_the_same_id_across_runs(tmp_path: Path) -> None:
    write_findings(tmp_path, "20261010T1-neatlogs-proposed", ["p-an-a"])
    write_findings(tmp_path, "20261010T2-neatlogs-proposed", ["p-an-b", "p-an-a"])
    f, run_dir = find_finding(tmp_path, "f")
    assert run_dir.name == "20261010T2-neatlogs-proposed"
    assert f["details"]["scenarios"] == ["p-an-b", "p-an-a"]
    assert f["details"]["runs"]["p-an-a"] == "20261010T2-neatlogs-proposed"
    with pytest.raises(FileNotFoundError):
        find_finding(tmp_path, "nope")


def test_code_path_prefix() -> None:
    assert pt.code_path_prefix("ag-run") == "ag-"
    assert pt.code_path_prefix("p-an-stream-helper-cut") == "p-an-"


def test_every_target_has_a_short_standalone_repro_and_meta() -> None:
    assert set(up.REPROS) == set(tg.TARGETS) == set(up.META)
    for key, script in up.REPROS.items():
        assert line_count(script) < up.MAX_REPRO_LINES, key
        assert "trueup" not in script  # standalone: the library and the SDK only
        compile(script, "repro.py", "exec")


def test_pr_text_without_a_verified_fix_proposes_nothing(tmp_path: Path) -> None:
    t = tg.TARGETS[("neatlogs", "anthropic messages stream")]
    text = up.pr_text({"details": {}}, t, {"fixed": False, "after_note": "no verified fix"}, tmp_path, None)
    assert "No PR is proposed" in text and "Not posted" in text


def test_cli_and_tracing_know_fix_and_upstream() -> None:
    p = build_parser()
    assert p.parse_args(["fix", "f-1"]).finding_id == "f-1"
    assert p.parse_args(["upstream", "f-1"]).command == "upstream"
    assert {"trueup-fixer", "trueup-verifier"} <= set(tracing.WORKERS)
