"""trueup audit <agent.py>: run a user's main() against the fake under one tracing library.

How it works:
  1. Run main() once with plain replies, to see which provider routes it calls.
  2. For each route it called, run main() once per fake scenario on that route
     (errors, cuts, tools, refusal, ...). Other routes keep plain replies.
  3. Compare truth (the fake's log and main()'s outcome) with the spans.

Limits:
  - main() must take no arguments and reach the provider through the openai or
    anthropic SDK, with clients that read OPENAI_BASE_URL / ANTHROPIC_BASE_URL
    (the default). A client with a hard-coded base_url is not redirected.
  - It runs in the library's venv, which has only the tracing library, openai
    and anthropic. A script that needs other packages will not import.
  - The fake answers every call on a route the same way. Agent loops that wait
    for a particular reply may stop early or loop until their own limit.
  - SDK retries are real requests: with the default max_retries a 500 is sent
    three times, and the call count check compares against all of them.
  - There is no scenario expectation, so the "library changed the request"
    note is not produced, and an app that stops reading a stream early is not
    detected (its output is still expected on the span).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from trueup import tracing
from trueup.core import report
from trueup.core.compare import compare
from trueup.core.model import Observation
from trueup.fake.server import SCENARIOS_BY_ROUTE
from trueup.runner import RAN, venvs
from trueup.runner.run import not_run, run_audit, run_record_audit
from trueup.state import State
from trueup.sweep import by_scenario, exit_code, new_run_id, summary_line

DISCOVER = "discover"


def load_mine(root: Path) -> list[dict[str, str]]:
    """Load reviewable custom cases from .trueup/cases/*.json."""
    case_dir = root / ".trueup" / "cases"
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in sorted(case_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text())
            case = {key: item[key] for key in ("id", "route", "scenario")}
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"invalid custom case {path}: {e}") from e
        if not all(isinstance(value, str) and value for value in case.values()):
            raise ValueError(f"invalid custom case {path}: id, route and scenario must be non-empty strings")
        if case["id"] in seen:
            raise ValueError(f"duplicate custom case id: {case['id']}")
        if case["route"] not in SCENARIOS_BY_ROUTE:
            raise ValueError(f"custom case {case['id']}: unsupported route {case['route']}")
        if case["scenario"] not in SCENARIOS_BY_ROUTE[case["route"]]:
            raise ValueError(f"custom case {case['id']}: {case['scenario']} is not valid for {case['route']}")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError(f"no custom cases in {case_dir}")
    return cases


def audit(
    root: Path,
    library: str,
    script: Path,
    *,
    ensure: Callable[[Path, str], Path] = venvs.ensure,
    run: Callable[..., dict[str, Any]] = run_audit,
    out: Callable[[str], None] = print,
    run_id: str | None = None,
    record_provider: str | None = None,
    upstream: str | None = None,
    record_run: Callable[..., dict[str, Any]] = run_record_audit,
    cases: str = "builtin",
) -> tuple[Path, list[dict[str, Any]]]:
    run_id = run_id or new_run_id(library).replace(f"-{library}", f"-audit-{library}")
    run_dir = root / ".trueup" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with State(root) as state:
        state.begin_run(run_id, "audit", library)
        with tracing.worker("trueup-runner", script=str(script)) as span:
            if not script.is_file():
                results.append(not_run(DISCOVER, library, f"no such file: {script}"))
                state.save_observation(run_id, DISCOVER, results[0])
            else:
                try:
                    out(f"preparing venv for {library}")
                    python = ensure(root, library)
                except Exception as e:  # noqa: BLE001 - reported as could not run
                    python = None
                    results.append(not_run(DISCOVER, library, f"venv not ready: {e}"))
                    state.save_observation(run_id, DISCOVER, results[0])
                if python is not None and record_provider:
                    cached = state.observation(run_id, "record")
                    if cached is not None:
                        out(f"{'record':30} resumed from state.db")
                        results = [cached]
                    elif not upstream:
                        results = [not_run("record", library, "TRUEUP_RECORD_UPSTREAM is not set")]
                        state.save_observation(run_id, "record", results[0])
                    else:
                        from trueup.recording import RecordingProxy

                        recording = run_dir / "recording.jsonl"
                        with RecordingProxy(upstream, recording) as proxy:
                            result = record_run(python, library, script, record_provider, proxy.base_url, recording)
                        state.save_observation(run_id, "record", result)
                        results = [result]
                elif python is not None:
                    results = _audit_runs(python, library, script, run, out, state, run_id,
                                          load_mine(root) if cases == "mine" else None)
            tracing.set_verdict(span, f"ran {sum(r['status'] == RAN for r in results)}/{len(results)}")
    with tracing.worker("trueup-comparer") as span:
        for r in results:
            if r["status"] == RAN:
                r["mismatches"] = [m.to_dict() for m in compare(Observation.from_dict(r["observation"]))]
        tracing.set_verdict(span, f"{sum(len(r.get('mismatches', [])) for r in results)} mismatches")
    for r in results:
        name = r["scenario"].replace("/", "_")
        (run_dir / f"{name}.json").write_text(json.dumps(r, indent=1, default=str))
    by = by_scenario(results)
    table = report.table(by)
    c = report.counts(by)
    not_run_list = [{"scenario": r["scenario"], "reason": r["reason"]} for r in results if r["status"] != RAN]
    (run_dir / "leads.json").write_text(json.dumps(report.leads_payload(run_id, library, by, not_run_list),
                                                   indent=1, default=str))
    (run_dir / "summary.txt").write_text("\n".join([
        f"trueup audit {script} --library {library} --cases {cases}"
        f"{f' --record --provider {record_provider}' if record_provider else ''}  run {run_id}",
        f"leads: {c['leads']}  by severity: {c['by_severity']}",
        "A lead is a disagreement between truth and trace, not a confirmed bug.",
        "",
        *(summary_line(r) for r in results),
        "",
        table,
    ]) + "\n")
    out("")
    out(table)
    out(f"leads: {c['leads']}  by severity: {c['by_severity']}; wrote {run_dir}")
    with State(root) as state:
        code = exit_code(results)
        state.finish_run(run_id, "mismatch" if code == 1 else "complete" if code == 0 else "error")
    return run_dir, results


def _audit_runs(python: Path, library: str, script: Path, run: Callable[..., dict[str, Any]],
                out: Callable[[str], None], state: State, run_id: str,
                custom: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    first = state.observation(run_id, DISCOVER)
    if first is None:
        first = run(python, library, script, DISCOVER, {})
        state.save_observation(run_id, DISCOVER, first)
    else:
        out(f"{DISCOVER:30} resumed from state.db")
    out(summary_line(first))
    if first["status"] != RAN:
        return [first]
    routes = sorted({e["path"] for e in first["observation"]["truth"]["fake_log"]} & set(SCENARIOS_BY_ROUTE))
    if not routes:
        return [not_run(DISCOVER, library, "main() made no provider call through the fake "
                        "(check that its clients use OPENAI_BASE_URL / ANTHROPIC_BASE_URL)")]
    out(f"main() calls: {', '.join(routes)}")
    results = []
    jobs = ([{"id": scenario, "route": route, "scenario": scenario}
             for route in routes for scenario in SCENARIOS_BY_ROUTE[route]] if custom is None else custom)
    for job in jobs:
        case_id, route, scenario = job["id"], job["route"], job["scenario"]
        if route not in routes:
            r = not_run(case_id, library, f"agent did not call custom case route {route}")
            state.save_observation(run_id, case_id, r)
            results.append(r)
            out(summary_line(r))
            continue
        r = state.observation(run_id, case_id)
        if r is None:
            r = run(python, library, script, case_id, {route: scenario})
            state.save_observation(run_id, case_id, r)
        else:
            out(f"{case_id:30} resumed from state.db")
        out(summary_line(r))
        results.append(r)
    return results
