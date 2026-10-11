"""Verify a patch: the package's own tests, the finding's scenarios, and the full scenario library.

Two venvs per library, both built from the clone in .trueup/clones/<lib>:
  .trueup/venvs/<lib>-fixtest-<package>  one per package: the package and its local dependencies
                               installed editable, with its test requirements; runs its own test
                               suite and the new test
  .trueup/venvs/<lib>-fix      the library as the scenarios use it (PACKAGES), its packages from
                               the clone; the "before" sweep runs on the clean clone, then each try
                               reinstalls the packages from the patched clone
The rules here are pure functions over recorded results; the effects are in the run_* helpers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from trueup.core import checker
from trueup.core.compare import compare, leads
from trueup.core.model import Observation
from trueup.fixer.targets import Package, Target
from trueup.runner import RAN, run_scenario, venvs
from trueup.runner.setups import PACKAGES

SECRET = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)


class VerifyError(RuntimeError):
    pass


def test_env() -> dict[str, str]:
    """The environment for a library's own tests: no keys of any kind, no outer venv."""
    env = {k: v for k, v in os.environ.items() if not SECRET.search(k)}
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    return env


def _uv() -> str:
    return shutil.which("uv") or "uv"


def _run(cmd: list[str], timeout: float = 1800, cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=test_env())
    if p.returncode != 0:
        raise VerifyError(f"{' '.join(cmd[:4])} failed: {(p.stderr or p.stdout).strip()[-800:]}")
    return p.stdout


def test_requirements(clone: Path, pkg: Package) -> list[str]:
    base = clone / pkg.path
    reqs: list[str] = []
    for dep in pkg.test_deps:
        if dep.startswith("group:"):
            groups = tomllib.loads((base / "pyproject.toml").read_text()).get("dependency-groups", {})
            reqs += [g for g in groups.get(dep[6:], []) if isinstance(g, str)]
        elif dep.startswith("file:"):
            for ln in (base / dep[5:]).read_text().splitlines():
                ln = ln.split("#", 1)[0].strip()
                if ln and not ln.startswith("-"):
                    reqs.append(ln)
        else:
            reqs.append(dep)
    return reqs


def ensure_test_venv(root: Path, clone: Path, library: str, pkg: Package) -> Path:
    """One venv per package: packages of one repo can pin conflicting test requirements."""
    d = venvs.venv_dir(root, f"{library}-fixtest-{Path(pkg.path).name or library}")
    py = d / "bin" / "python"
    stamp = {"package": pkg.path, "local": list(pkg.local_deps), "deps": list(pkg.test_deps)}
    if py.exists() and (d / venvs.STAMP).exists() and json.loads((d / venvs.STAMP).read_text()) == stamp:
        return py
    _run([_uv(), "venv", "--quiet", "--allow-existing", "--python", "3.12", str(d)])
    # Local packages of the repo, editable, replace any PyPI release a test requirement pulls in.
    local = [*pkg.local_deps, pkg.path]
    _run([_uv(), "pip", "install", "--quiet", "--python", str(py), *test_requirements(clone, pkg),
          *(a for x in local for a in ("-e", str(clone / x)))])
    (d / venvs.STAMP).write_text(json.dumps(stamp))
    return py


def parse_junit(path: Path) -> dict[str, Any]:
    """Counts and the ids of failed/errored tests from a pytest junit xml."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    total = failed = errors = skipped = 0
    bad: list[str] = []
    ids: list[str] = []
    for s in suites:
        for tc in s.iter("testcase"):
            total += 1
            tid = f"{tc.get('classname', '')}::{tc.get('name', '')}"
            ids.append(tid)
            if tc.find("failure") is not None:
                failed += 1
                bad.append(tid)
            elif tc.find("error") is not None:
                errors += 1
                bad.append(tid)
            elif tc.find("skipped") is not None:
                skipped += 1
    return {"total": total, "passed": total - failed - errors - skipped, "failed": failed, "errors": errors,
            "skipped": skipped, "failing": sorted(set(bad)), "tests": ids}


def run_pytest(py: Path, clone: Path, pkg: Package, args: list[str], timeout: float = 2400) -> dict[str, Any]:
    """pytest in the package dir. Records the exit code, counts, failing ids and the output tail."""
    cwd = clone / pkg.path
    junit = cwd / ".trueup-junit.xml"
    junit.unlink(missing_ok=True)
    cmd = [str(py), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:sugar", "-p", "no:warnings", "--tb=short",
           "-rfE", "--continue-on-collection-errors", f"--junitxml={junit}",
           *args]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=test_env())
        text = (p.stdout + p.stderr).strip()
        code, tail = p.returncode, text[-3000:]
    except subprocess.TimeoutExpired:
        code, tail = -1, f"timed out after {timeout:.0f} s"
        text = tail
    res: dict[str, Any] = {"cmd": " ".join(["pytest", *args]), "cwd": pkg.path, "exit": code, "tail": tail,
                           "brief": brief(text)}
    if junit.exists():
        res.update(parse_junit(junit))
        junit.unlink()
    return res


def brief(text: str, limit: int = 1500) -> str:
    """The lines that say why tests failed: the `file:line: in test` locations, the `E ` lines and the
    FAILED/ERROR summary. v1 sent the last 1200 characters of the output instead, which often held
    warnings and captured logs (sessions 20261011T001405Z-fix-openllmetry and
    20261011T004013Z-fix-openinference, try 1: "PydanticDeprecatedSince20 ...", "Captured log call")."""
    keep = [ln for ln in text.splitlines() if ln.startswith(("E ", "FAILED", "ERROR ")) or
            (": in test" in ln and ln.lstrip().startswith(("tests/", "test")))]
    out, n = [], 0
    for ln in keep:
        if n + len(ln) > limit:
            break
        out.append(ln)
        n += len(ln) + 1
    return "\n".join(out)


def baseline_usable(before: dict[str, Any]) -> tuple[bool, str]:
    """The suite must really run on the clean clone, or a patch cannot be judged by it."""
    if "failing" not in before or before["exit"] not in (0, 1) or before.get("passed", 0) == 0:
        return False, (f"the package's own test suite does not run on the clean clone (exit {before['exit']}, "
                       f"{before.get('passed', 0)} passed): {before['tail'][-500:]}")
    return True, f"{before['passed']} passed, {len(before['failing'])} failing before the patch"


def suite_verdict(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
    """The suite passes, or fails only where it failed before the patch. The new test counts too:
    a test that passes alone but fails inside the suite is a failure."""
    if "failing" not in after:
        return False, f"the suite did not run after the patch (exit {after['exit']}): {after['tail'][-400:]}"
    new = [t for t in after["failing"] if t not in set(before.get("failing", []))]
    if new:
        return False, (f"{len(new)} test(s) fail in the full suite after the patch and did not fail before: "
                       f"{', '.join(new[:10])}. Output: {after['tail'][-1200:]}")
    if after["total"] < before.get("total", 0):
        return False, f"fewer tests ran after the patch ({after['total']} vs {before['total']})"
    same = len(after["failing"])
    return True, ("suite passes" if not same else f"same {same} failure(s) as before the patch")


def new_test_verdict(before: dict[str, Any], after: dict[str, Any], variant: str = "v1") -> tuple[bool, str]:
    """The new test must fail on the unpatched code and pass on the patched code."""
    if variant == "v2" and after.get("brief") and (after.get("total", 0) == 0 or after.get("failing")) \
            and before.get("total", 0) and before.get("failing"):
        return False, (f"the new test fails with the patch (exit {after['exit']}). Why, from pytest:\n"
                       f"{after['brief']}\nLast lines:\n{after['tail'][-300:]}")
    if before.get("total", 0) == 0:
        return False, f"the new test was not collected before the patch (exit {before['exit']}): " \
                      f"{before['tail'][-600:]}"
    if not before["failing"]:
        return False, "the new test passes on the unpatched code, so it does not show the bug"
    if after.get("total", 0) == 0 or after["failing"]:
        return False, f"the new test fails with the patch (exit {after['exit']}): {after['tail'][-1200:]}"
    weak = [t.rsplit("::", 1)[-1] for t in before.get("tests", []) if t not in before["failing"]]
    note = (f"; {len(weak)} of {before['total']} new test functions also pass before the patch, so they do not "
            f"show the bug: {', '.join(weak)}") if weak else ""
    return True, (f"new test: fails before ({len(before['failing'])} of {before['total']} failing), passes after "
                  f"({after['total']} passed){note}")


# The scenario side ------------------------------------------------------------------

def ensure_fix_venv(root: Path, clone: Path, library: str) -> Path:
    """PACKAGES from PyPI, with the library's packages from the clone (non-editable)."""
    d = venvs.venv_dir(root, f"{library}-fix")
    py = d / "bin" / "python"
    paths: dict[str, str] = venvs.MAIN_SOURCES[library]["paths"]  # type: ignore[assignment]
    if not py.exists():
        _run([_uv(), "venv", "--quiet", "--allow-existing", "--python", "3.12", str(d)])
    pypi = [p for p in PACKAGES[library] if p not in paths]
    _run([_uv(), "pip", "install", "--quiet", "--python", str(py), *pypi, *(str(clone / p) for p in paths.values())])
    return py


def reinstall(py: Path, clone: Path, target: Target) -> None:
    """Put the clone's current (patched) packages into the -fix venv."""
    _run([_uv(), "pip", "install", "--quiet", "--no-deps", "--reinstall", "--python", str(py),
          *(str(clone / p.path) for p in target.packages)])


def sweep_scenarios(py: Path, library: str, scenario_ids: list[str],
                    run: Callable[..., dict[str, Any]] = run_scenario,
                    out: Callable[[str], None] = print) -> dict[str, Any]:
    """Run scenarios in the venv; leads per scenario (as dicts) and NOT RUN reasons."""
    res: dict[str, Any] = {"leads": {}, "not_run": {}, "spans": {}}
    for sid in scenario_ids:
        r = run(py, library, sid)
        if r["status"] != RAN:
            res["not_run"][sid] = r["reason"]
            out(f"    {sid:30} NOT RUN {r['reason']}")
            continue
        ls = [m.to_dict() for m in leads(compare(Observation.from_dict(r["observation"])))]
        res["leads"][sid] = ls
        res["spans"][sid] = compact_spans(r["observation"]["trace"]["spans"])
        out(f"    {sid:30} {len(ls)} lead(s)")
    return res


def compact_spans(spans: list[dict[str, Any]]) -> list[list[Any]]:
    """[name, status, description, parent name] per span."""
    names = {s.get("span_id"): s["name"] for s in spans}
    return [[s["name"], s["status"]["code"], (s["status"].get("description") or "")[:80], names.get(s.get("parent_id"))]
            for s in spans]


def matches_finding(lead: dict[str, Any], finding: dict[str, Any]) -> bool:
    d = finding["details"]
    return lead.get("check") == d["check"] and lead.get("field") == d["field"]


def scenario_verdict(after: dict[str, Any], finding: dict[str, Any]) -> tuple[bool, str]:
    """Every scenario of the finding ran and none still shows the finding's lead."""
    bad, missing = [], []
    for sid in finding["details"]["scenarios"]:
        if sid not in after["leads"]:
            missing.append(sid)
        elif any(matches_finding(m, finding) for m in after["leads"][sid]):
            bad.append(sid)
    if missing:
        return False, f"scenario(s) did not run: {', '.join(missing)}"
    if bad:
        shown = [f"{sid}: truth {m['truth']}, trace {m['trace']}" for sid in bad for m in after["leads"][sid]
                 if matches_finding(m, finding)]
        spans = "; ".join(f"{sid}: {after.get('spans', {}).get(sid)}" for sid in bad[:2])
        return False, (f"still wrong after the patch: {', '.join(bad)}. With the patch installed and the real "
                       f"scenario run, {finding['details']['field']}: " + "; ".join(shown[:5]) +
                       f". Spans exported with the patch ([name, status, description, parent]): {spans}")
    return True, f"all {len(finding['details']['scenarios'])} scenario(s) of the finding now match truth here"


def new_mismatches(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Leads after the patch whose signature was not there before, per scenario. NOT RUN after counts too."""
    out = []
    for sid, ls in after["leads"].items():
        old = {json.dumps(checker.signature(m)) for m in before["leads"].get(sid, [])}
        out += [{**m, "scenario": sid} for m in ls if json.dumps(checker.signature(m)) not in old]
    out += [{"scenario": sid, "check": "not_run", "field": "-", "truth": "ran before", "trace": reason}
            for sid, reason in after["not_run"].items() if sid not in before["not_run"]]
    return out


def before_after(finding: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for sid in finding["details"]["scenarios"]:
        b = next((m for m in before["leads"].get(sid, []) if matches_finding(m, finding)), None)
        a = next((m for m in after["leads"].get(sid, []) if matches_finding(m, finding)), None)
        truth = (b or a or {}).get("truth", "?")
        rows.append({"scenario": sid, "field": finding["details"]["field"], "truth": truth,
                     "before": b["trace"] if b else "matches truth",
                     "after": a["trace"] if a else ("not run" if sid in after["not_run"] else "matches truth")})
    return rows


def totals(sweep: dict[str, Any]) -> dict[str, Any]:
    ls = [m for v in sweep["leads"].values() for m in v]
    return {"scenarios_ran": len(sweep["leads"]), "not_run": len(sweep["not_run"]), "leads": len(ls),
            "high": sum(m.get("severity") == "high" for m in ls),
            "medium": sum(m.get("severity") == "medium" for m in ls)}


def table_md(rows: list[dict[str, Any]], tb: dict[str, Any], ta: dict[str, Any]) -> str:
    lines = ["| scenario | field | truth | before | after |", "|---|---|---|---|---|"]
    lines += [f"| {r['scenario']} | {r['field']} | {r['truth']} | {r['before']} | {r['after']} |" for r in rows]
    lines += ["", "Full scenario library for this library (same venv, before and after the patch):", "",
              "| | scenarios ran | not run | leads | high | medium |", "|---|---|---|---|---|---|"]
    for name, t in (("before", tb), ("after", ta)):
        lines.append(f"| {name} | {t['scenarios_ran']} | {t['not_run']} | {t['leads']} | {t['high']} | "
                     f"{t['medium']} |")
    return "\n".join(lines) + "\n"
