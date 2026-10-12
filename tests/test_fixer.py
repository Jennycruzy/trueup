"""Offline tests for the fixer, the verifier rules and the upstream drafts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trueup import tracing
from trueup.cli import build_parser
from trueup.core.repro import line_count
from trueup.fix import checkpointed_draft, find_finding, write_log
from trueup.state import State
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


def test_paid_fixer_draft_is_reused_after_restart(tmp_path: Path) -> None:
    class Client:
        def __init__(self):
            self.calls = 0

        def chat_json(self, *args, **kwargs):
            self.calls += 1
            return {"edits": [{"file": "x", "old": "a", "new": "b"}], "test": {"file": "t", "content": "x"}}

    with State(tmp_path) as state:
        state.begin_run("fix-run", "fix", "finding")
    first, second = Client(), Client()
    one = checkpointed_draft(tmp_path, "fix-run", 1, first, [], "v2")
    two = checkpointed_draft(tmp_path, "fix-run", 1, second, [], "v2")
    assert one == two
    assert first.calls == 1 and second.calls == 0


def test_v3_fixer_requests_proxy_json_mode(tmp_path: Path) -> None:
    class Client:
        def __init__(self):
            self.kwargs = None

        def chat_json(self, *args, **kwargs):
            self.kwargs = kwargs
            return {"edits": [], "test": {}}

    with State(tmp_path) as state:
        state.begin_run("fix-v3", "fix", "finding")
    client = Client()
    checkpointed_draft(tmp_path, "fix-v3", 1, client, [], "v3")
    assert client.kwargs["lenient"] is True
    assert client.kwargs["strict"] is True


def test_v3_fixer_uses_the_committed_json_only_prompt(repo: Path) -> None:
    finding = {"id": "f", "title": "wrong trace", "severity": "high", "details": {
        "check": "run_status", "field": "status", "leads": [], "scenarios": ["s"], "rules": {}}}
    located = {"commit": "abcdef012345", "definitions": [], "callers": []}
    messages = pt.first_prompt(finding, TARGET, located, "source", "style", variant="v3")
    assert messages[0]["content"] == (Path(__file__).parents[1] / "prompts/fixer-v3.txt").read_text()


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


def fake_graph(missing: bool = False, python: bool = True):
    """A stand-in for `entire graph` returning JSON shaped like CLI 0.11.4's output."""
    import subprocess

    calls = []

    def run(cmd, cwd, timeout):
        calls.append(cmd)
        if cmd[0] != "entire":
            return loc.run_cmd(cmd, cwd, timeout)
        if missing:
            return subprocess.CompletedProcess(cmd, 1, "", "the entire-graph plugin is not installed")
        sub = cmd[2]
        if sub == "capabilities":
            out = {"schema_version": "1.1", "semantic_languages": ["Python"] if python else [],
                   "relation_support_by_language": {"Python": ["CALLS"]}}
        elif sub == "search":
            out = {"repo_root": str(cwd / cmd[cmd.index("--repo") + 1]), "results": [
                {"kind": "method", "symbol_name": "wrap", "qualified_name": "P.wrap", "file_path": "lib/w.py",
                 "start_line": 5, "end_line": 6, "score": 9.0},
                {"kind": "function", "symbol_name": "top", "qualified_name": "top", "file_path": "lib/w.py",
                 "start_line": 12, "end_line": 13, "score": 5.0},
                {"kind": "function", "symbol_name": "t", "qualified_name": "t", "file_path": "tests/t.py",
                 "start_line": 1, "end_line": 2, "score": 99.0}]}
        elif sub == "neighbors":
            out = {"repo_root": str(cwd), "matches": [{"incoming": [{"endpoint": {
                "qualified_name": "top", "file_path": "lib/w.py", "start_line": 12},
                "evidence": [{"detail": "P().wrap"}], "confidence": 0.9}]}]}
        else:
            out = {"repo_root": str(cwd), "match_bodies": []}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    return run, calls


def test_locate_uses_the_graph_first_and_writes_no_absolute_paths(repo: Path, tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    which = loc.shutil.which
    monkeypatch.setattr(loc.shutil, "which", lambda name: "/bin/entire" if name == "entire" else which(name))
    monkeypatch.setattr(loc, "ensure_clone", lambda root, lib, run=None: (repo, "abc123"))
    run, calls = fake_graph()
    out = tmp_path / "out"
    res = loc.locate(repo, TARGET, out, run, finding=None)
    assert res["method"] == "entire graph + seed symbols" and res["graph"]["used"]
    assert [(d["file"], d["qualname"], d["rank"]) for d in res["definitions"]] == [
        ("pkg/lib/w.py", "P.wrap", 1), ("pkg/lib/w.py", "top", 2)]  # test hits dropped, paths from the clone
    assert res["callers"][0]["in"] == "top" and res["callers"][0]["file"] == "pkg/lib/w.py"
    subs = [c[2] for c in calls if c[0] == "entire"]
    assert subs[:2] == ["capabilities", "search"] and "neighbors" in subs and "impact" in subs
    text = (out / "locate.json").read_text()
    assert str(repo) not in text and str(Path.home()) + "/" not in text
    assert json.loads(text)["clone"] == ".trueup/clones/lib"


def test_locate_keeps_seed_definition_when_graph_hits_are_off_target(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    which = loc.shutil.which
    monkeypatch.setattr(loc.shutil, "which", lambda name: "/bin/entire" if name == "entire" else which(name))
    monkeypatch.setattr(loc, "ensure_clone", lambda root, lib, run=None: (repo, "abc123"))
    run, _ = fake_graph()
    target = tg.Target(library="lib", code_path="x", packages=(tg.Package("pkg", "pkg"),),
                       seeds=("use",), reference_seeds=())

    res = loc.locate(repo, target, tmp_path / "out", run)

    assert res["definitions"][0]["qualname"] == "P.wrap"  # ranked graph result remains first
    assert any(d["qualname"] == "P.use" for d in res["definitions"])
    assert "def use(self)" in loc.source_excerpts(repo, res)


@pytest.mark.parametrize("missing, python, reason", [(True, True, "not available"), (False, False, "Python")])
def test_locate_falls_back_and_says_why(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                        missing: bool, python: bool, reason: str) -> None:
    which = loc.shutil.which
    monkeypatch.setattr(loc.shutil, "which", lambda name: "/bin/entire" if name == "entire" else which(name))
    monkeypatch.setattr(loc, "ensure_clone", lambda root, lib, run=None: (repo, "abc123"))
    run, _ = fake_graph(missing, python)
    res = loc.locate(repo, TARGET, tmp_path / "out", run)
    assert res["method"] == "ripgrep + ast (fallback)" and not res["graph"]["used"]
    assert reason in res["graph"]["reason"]
    assert [d["qualname"] for d in res["definitions"]] == ["P.wrap"]


def test_scrub_makes_paths_relative() -> None:
    root = Path("/x/trueup")
    text = f"{root}/.trueup/clones/lib/a.py and {root} and {Path.home()}/.local/bin/uv"
    assert loc.scrub(text, root, root / ".trueup/clones/lib") == "a.py and . and ~/.local/bin/uv"


DIFF = """--- a/pkg/lib/w.py
+++ b/pkg/lib/w.py
@@ -4,4 +4,5 @@ class P:
     def wrap(self, x):
-        return x
+        y = x
+        return y
 
--- a/pkg/tests/test_trueup_w.py
+++ b/pkg/tests/test_trueup_w.py
@@ -0,0 +1 @@
+def test(): pass
"""


def test_patched_functions_and_compare(repo: Path) -> None:
    patched = loc.patched_functions(repo, DIFF)
    assert patched == [{"file": "pkg/lib/w.py", "qualname": "P.wrap"}]
    located = {"definitions": [{"file": "pkg/lib/w.py", "qualname": "top", "rank": 1},
                               {"file": "pkg/lib/w.py", "qualname": "P", "rank": 2}],
               "callers": [{"in": "P.wrap"}]}
    c = loc.compare_with_patch(located, patched)
    assert c["patched"][0]["rank"] is None and c["patched"][0]["class_rank"] == 2
    assert c["patched"][0]["among_callers"] and c["found"] == 0 and not c["same_function_first"]
    c = loc.compare_with_patch({"definitions": [{"file": "pkg/lib/w.py", "qualname": "P.wrap", "rank": 1}],
                                "callers": []}, patched)
    assert c["same_function_first"] and c["in_top"] == 1


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
    assert ok and "test_b" in why and "guards" in why and "do not show the bug" in why
    assert not vf.new_test_verdict({**before, "failing": []}, {"total": 2, "failing": [], "exit": 0, "tail": ""})[0]
    assert not vf.new_test_verdict(before, {"total": 2, "failing": ["m::test_a"], "exit": 1, "tail": ""})[0]
    assert not vf.new_test_verdict({"total": 0, "exit": 4, "tail": ""}, {"total": 1, "failing": []})[0]


def test_magicmock_style_all_pass_test_is_rejected_as_guard_only() -> None:
    before = {"total": 2, "failing": [], "tests": ["m::test_mock_called", "m::test_shape"],
              "exit": 0, "tail": "2 passed"}
    ok, why = vf.new_test_verdict(before, {**before, "tail": "2 passed"})
    assert not ok and "does not show the bug" in why


def test_failed_fix_log_preserves_proven_artifacts_byte_for_byte(tmp_path: Path) -> None:
    fix_dir, run_dir = tmp_path / "fixes" / "f", tmp_path / "runs" / "r2"
    fix_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    names = ["patch.diff", "test_trueup_fix.py", "before-after.json", "before-after.md",
             "tries.json", "suites.json", "summary.md"]
    before = {}
    for i, name in enumerate(names):
        payload = (f"proven-{i}\n").encode()
        (fix_dir / name).write_bytes(payload)
        before[name] = payload
    result = {"run_id": "r2", "tries": [], "finding": "f", "title": "failed rerun",
              "model": "m", "cost_usd": 0, "fixed": False, "error": None}
    write_log(fix_dir, run_dir, result, publish=False)
    assert {name: (fix_dir / name).read_bytes() for name in names} == before
    assert (fix_dir / "runs" / "r2.json").exists()


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


def test_v2_brief_keeps_why_a_test_failed():
    from trueup.fixer.verify import brief, new_test_verdict

    out = ("....\nwarnings: PydanticDeprecatedSince20 ...\n" * 50 +
           "tests/test_trueup_x.py:12: in test_root\n    assert s == ERROR\nE   AssertionError: expected ERROR got OK\n"
           "------ Captured log call ------\nERROR openai.agents: noise\n" * 1 +
           "FAILED tests/test_trueup_x.py::test_root - AssertionError\n")
    b = brief(out)
    assert "E   AssertionError: expected ERROR got OK" in b and "FAILED tests/test_trueup_x.py::test_root" in b
    assert "Pydantic" not in b
    before = {"total": 1, "failing": ["t"], "exit": 1, "tail": out[-3000:], "brief": b}
    after = {"total": 1, "failing": ["t"], "exit": 1, "tail": out[-3000:], "brief": b}
    ok, why = new_test_verdict(before, after, "v2")
    assert not ok and "AssertionError: expected ERROR got OK" in why
    ok, why1 = new_test_verdict(before, after, "v1")
    assert not ok and "Why, from pytest" not in why1


def test_v2_revision_sends_only_the_last_draft():
    from trueup.fixer.patch import revision_prompt, revision_prompt_v2

    first = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    v1 = revision_prompt(revision_prompt(first, {"d": 1}, "r1"), {"d": 2}, "r2")
    v2 = revision_prompt_v2(first, {"d": 2}, "r2", ["r1"])
    assert len(v1) == 6 and len(v2) == 4
    assert '"d": 1' not in json.dumps(v2) and "try 1: r1" in v2[-1]["content"]
