"""trueup check <run_id|latest> [--library x]: run the checker and dedupe over a sweep's leads.

This module gathers the evidence (the effects); the rules in trueup.core.checker
decide. Steps, one library at a time:
  1. bring the library's venv to the latest release and record versions against PyPI
  2. rerun every scenario with a lead twice, each in a fresh process
  3. build .trueup/venvs/<lib>-main from a shallow clone of main and run the scenarios there
  4. read the other libraries' latest sweeps of the same scenarios (compared again with
     today's adapters)
  5. generate a repro per scenario and run it
  6. apply the rules, group findings by cause, search GitHub for each finding (read only)
Writes findings.json, withdrawn.json and evidence.json next to the sweep's leads.json.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trueup import dedupe, tracing
from trueup.core import checker, group, repro
from trueup.core.compare import compare, leads
from trueup.core.model import Observation
from trueup.runner import RAN, run_scenario, venvs
from trueup.runner.run import child_env
from trueup.runner.setups import LIBRARIES
from trueup.scenarios import get
from trueup.state import State

# The distributions that are the library itself (checked against PyPI's latest).
LIB_DISTS = {
    "neatlogs": ("neatlogs",),
    "openinference": tuple(f"openinference-instrumentation-{n}" for n in ("openai", "anthropic", "langchain",
                                                                           "openai-agents")),
    "openllmetry": ("traceloop-sdk", *(f"opentelemetry-instrumentation-{n}" for n in ("openai", "anthropic",
                                                                                         "langchain", "openai-agents"))),
}
SETUP_NAMES = {
    "neatlogs": "neatlogs.init(instrumentations=<README keys>)",
    "openinference": "the OpenInference instrumentor for the SDK or framework",
    "openllmetry": "Traceloop.init()",
}
HARNESS_ENV = ("NEATLOGS_DISABLE_EXPORT", "NEATLOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT",
               "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_TRACES_EXPORTER", "TRACELOOP_BASE_URL")


def sweeps(root: Path, library: str | None) -> list[Path]:
    """Sweep run dirs (leads.json, not audits), oldest first. Proposed-scenario sweeps end in -proposed."""
    runs = root / ".trueup" / "runs"
    return sorted(d for d in runs.glob("*") if (d / "leads.json").exists() and "-audit-" not in d.name
                  and (library is None or d.name.endswith((f"-{library}", f"-{library}-proposed"))))


def find_run(root: Path, run_id: str, library: str | None) -> Path:
    runs = root / ".trueup" / "runs"
    if run_id != "latest":
        d = runs / run_id
        if not (d / "leads.json").exists():
            raise FileNotFoundError(f"no leads.json in {d}")
        return d
    cands = sweeps(root, library)
    if not cands:
        raise FileNotFoundError(f"no sweep with leads.json for {library or 'any library'}")
    return cands[-1]


def _lead_dicts(library: str, scenario: str, mismatches: list[Any]) -> list[dict[str, Any]]:
    return [{**m.to_dict(), "scenario": scenario, "library": library} for m in leads(mismatches)]


def _sigs(observation: dict[str, Any]) -> list[list[Any]]:
    return [checker.signature(m.to_dict()) for m in leads(compare(Observation.from_dict(observation)))]


def _run_record(r: dict[str, Any], framework: str, library: str) -> dict[str, Any]:
    rec = {"status": r["status"], "reason": r["reason"], "seconds": r["seconds"], "framework": framework,
           "setup": SETUP_NAMES[library]}
    if r["status"] == RAN:
        rec["leads"] = _sigs(r["observation"])
        rec["versions"] = r["observation"]["trace"].get("versions", {})
    return rec


def pypi_latest(dist: str) -> str | None:
    import httpx

    try:
        r = httpx.get(f"https://pypi.org/pypi/{dist}/json", timeout=20)
        return r.json()["info"]["version"] if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def other_runs(root: Path, library: str) -> dict[str, list[Path]]:
    """Sweep run dirs per other library, newest first."""
    return {lib: sweeps(root, lib)[::-1] for lib in LIBRARIES if lib != library and sweeps(root, lib)}


def other_evidence(dirs: dict[str, list[Path]], scenario: str) -> dict[str, Any]:
    """Each other library's newest sweep of this scenario."""
    out: dict[str, Any] = {}
    for lib, ds in dirs.items():
        d = next((d for d in ds if (d / f"{scenario}.json").exists()), None)
        if d is None:
            out[lib] = {"status": "missing", "run": ds[0].name}
            continue
        r = json.loads((d / f"{scenario}.json").read_text())
        out[lib] = {"status": r["status"], "run": d.name,
                    "leads": _sigs(r["observation"]) if r["status"] == RAN else []}
    return out


def run_repro(python: Path, path: Path, timeout: float = 120) -> dict[str, Any]:
    text = path.read_text()
    rec: dict[str, Any] = {"path": str(path), "lines": repro.line_count(text)}
    with tempfile.TemporaryDirectory(prefix="trueup-repro-") as tmp:
        try:
            p = subprocess.run([str(python.absolute()), str(path.resolve())], env=child_env(), cwd=tmp, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {**rec, "status": "not_run", "reason": f"timed out after {timeout:.0f} s"}
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()
        return {**rec, "status": "not_run", "reason": f"exit {p.returncode}: {tail[-1] if tail else ''}"}
    found = []
    for line in p.stdout.splitlines():
        try:
            found.append(checker.signature(json.loads(line)))
        except (ValueError, KeyError):
            continue
    return {**rec, "status": "ran", "exit": p.returncode, "leads": found}


def gather(root: Path, run_dir: Path, library: str, out: Callable[[str], None] = print,
           run: Callable[..., dict[str, Any]] = run_scenario) -> list[dict[str, Any]]:
    """Evidence per lead in the sweep."""
    payload = json.loads((run_dir / "leads.json").read_text())
    by_scenario: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for s in payload["scenarios"]:
        r = json.loads((run_dir / f"{s['scenario']}.json").read_text())
        if r["status"] != RAN:
            continue
        # Compare again with today's adapters, so an adapter fix applies to old sweeps.
        ls = _lead_dicts(library, s["scenario"], compare(Observation.from_dict(r["observation"])))
        if ls:
            by_scenario[s["scenario"]] = (r["observation"], ls)
    total = sum(len(v[1]) for v in by_scenario.values())
    out(f"{library}: {total} leads in {len(by_scenario)} scenarios ({run_dir.name})")

    out("upgrading the venv to the latest release")
    py = venvs.upgrade(root, library)
    pypi = {d: pypi_latest(d) for d in LIB_DISTS[library]}
    out("building the main-branch venv")
    try:
        main_py, commit = venvs.ensure_main(root, library)
        main_error = None
    except Exception as e:  # noqa: BLE001 - recorded as "could not check"
        main_py, commit, main_error = None, "", f"could not install main: {e}"
    others = other_runs(root, library)
    harness = {"env": {k: v for k, v in child_env().items() if k in HARNESS_ENV}}
    repro_dir = run_dir / "repros"
    repro_dir.mkdir(exist_ok=True)
    cache_dir = run_dir / "check-cache"
    cache_dir.mkdir(exist_ok=True)

    evidence = []
    for sid, (obs, ls) in by_scenario.items():
        s = get(sid)
        t0 = time.monotonic()
        # Per-scenario cache, so an interrupted check resumes. Valid for the same main commit.
        cached = cache_dir / f"{sid}.json"
        if cached.exists() and json.loads(cached.read_text()).get("commit") == commit:
            reruns, main, rp = (json.loads(cached.read_text())[k] for k in ("reruns", "main", "repro"))
        else:
            reruns = [_run_record(run(py, library, sid), s.framework, library) for _ in range(2)]
            if main_py is None:
                main = {"status": "could_not_install", "reason": main_error}
            else:
                m = _run_record(run(main_py, library, sid), s.framework, library)
                main = {**m, "commit": commit, "reason": m["reason"] and f"main run: {m['reason']}"}
            path = repro_dir / f"{library}-{sid}.py"
            path.write_text(repro.generate(library, sid, s.does))
            rp = run_repro(py, path)
            rp["path"] = str(path.relative_to(root.resolve()))
            cached.write_text(json.dumps({"commit": commit, "reruns": reruns, "main": main, "repro": rp},
                                         default=str))
        installed = (reruns[0].get("versions") or {}) if reruns else {}
        latest = {"installed": {d: installed.get(d) for d in LIB_DISTS[library] if installed.get(d)}, "pypi": pypi}
        oth = other_evidence(others, sid)
        scen = {"id": sid, "framework": s.framework, "provider": s.provider, "api": s.api, "app": s.app}
        for lead in ls:
            evidence.append({"lead": lead, "scenario": scen, "observation": obs, "reruns": reruns, "latest": latest,
                             "main": main, "harness": harness, "others": oth, "repro": rp})
        out(f"  {sid:28} {len(ls)} lead(s) checked in {time.monotonic() - t0:.0f} s")
    return evidence


def decide(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for ev in evidence:
        results = checker.run_rules(ev)
        status, by = checker.verdict(results)
        items.append({"lead": ev["lead"], "scenario": ev["scenario"], "status": status,
                      "rules": [r.to_dict() for r in results], "decided_by": by.to_dict() if by else None})
    return items


def check(root: Path, run_id: str, library: str | None, out: Callable[[str], None] = print,
          search: Callable[[list[str]], str] = dedupe.gh_search,
          state_run_id: str | None = None) -> dict[str, Any]:
    run_dir = find_run(root, run_id, library)
    lib = json.loads((run_dir / "leads.json").read_text())["library"]
    state_run_id = state_run_id or f"check-{run_dir.name}"
    with State(root) as state:
        state.begin_run(state_run_id, "check", lib)
    if library and lib != library:
        raise ValueError(f"{run_dir.name} is a {lib} sweep, not {library}")
    with tracing.worker("trueup-checker") as span:
        evidence = gather(root, run_dir, lib, out)
        items = decide(evidence)
        findings = group.group([i for i in items if i["status"] == checker.FINDING])
        tracing.set_verdict(span, f"{len(findings)} findings from {len(items)} leads")
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out("searching GitHub issues and PRs (read only)")
    with tracing.worker("trueup-deduper") as span:
        known = dedupe.dedupe(lib, findings, search)
        tracing.set_verdict(span, f"{sum(k['status'] == 'already known' for k in known.values())} already known")
    finding_dicts = [{**f.to_dict(), "dedupe": known[f.id]} for f in findings]
    disputed = [f.to_dict() for f in group.group([i for i in items if i["status"] == checker.DISPUTED_SEMANTICS])]
    open_leads = [i for i in items if i["status"] == checker.LEAD]
    withdrawn = [i for i in items if i["status"] == checker.WITHDRAWN]

    counts = {
        "leads": len(items),
        "finding_leads": sum(i["status"] == checker.FINDING for i in items),
        "findings": len(findings),
        "findings_by_severity": dict(Counter(f.severity.value for f in findings)),
        "disputed": len(disputed),
        "open_leads": len(open_leads),
        "withdrawn": len(withdrawn),
        "withdrawn_by_rule": dict(Counter(i["decided_by"]["rule"] for i in withdrawn)),
        "already_known": sum(k["status"] == "already known" for k in known.values()),
    }
    common = {"run_id": run_dir.name, "library": lib, "checked_at": checked_at}
    (run_dir / "findings.json").write_text(json.dumps({
        **common, "counts": counts, "findings": finding_dicts, "disputed_semantics": disputed,
        "open_leads": open_leads}, indent=1, default=str))
    (run_dir / "withdrawn.json").write_text(json.dumps({
        **common, "note": "Withdrawn leads are kept and counted, never deleted.", "withdrawn": withdrawn},
        indent=1, default=str))
    (run_dir / "evidence.json").write_text(json.dumps(
        [{k: v for k, v in ev.items() if k != "observation"} for ev in evidence], indent=1, default=str))
    with State(root) as state:
        state.save_check_results(state_run_id, items, finding_dicts, withdrawn)
        state.finish_run(state_run_id, "mismatch" if findings else "complete")
    out(summary(lib, counts, finding_dicts))
    out(f"wrote {run_dir}/findings.json, withdrawn.json, evidence.json")
    return {"run_dir": run_dir, "counts": counts, "state_run_id": state_run_id}


def summary(library: str, counts: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    sev = counts["findings_by_severity"]
    lines = [
        f"{library}: {counts['leads']} leads -> {counts['findings']} findings "
        f"({counts['finding_leads']} leads), {counts['withdrawn']} withdrawn, "
        f"{counts['disputed']} disputed semantics, {counts['open_leads']} still leads",
        "",
        "findings by severity: " + ", ".join(f"{s} {sev.get(s, 0)}" for s in ("high", "medium", "low")),
        "withdrawn by rule:    " + (", ".join(f"{r} {n}" for r, n in sorted(counts["withdrawn_by_rule"].items()))
                                    or "none"),
        f"already known:        {counts['already_known']}",
        "",
    ]
    rows = [("severity", "scenarios", "known", "finding")]
    for f in findings:
        k = f["dedupe"]
        rows.append((f["severity"].upper(), str(len(f["details"]["scenarios"])),
                     k["links"][0] if k["status"] == "already known" else "-", f["title"]))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    lines += ["  ".join([*(c.ljust(w) for c, w in zip(r[:3], widths)), r[3]]) for r in rows]
    return "\n".join(lines)
