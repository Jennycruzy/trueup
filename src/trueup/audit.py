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

from trueup.core import report
from trueup.core.compare import compare
from trueup.core.model import Observation
from trueup.fake.server import SCENARIOS_BY_ROUTE
from trueup.runner import RAN, venvs
from trueup.runner.run import not_run, run_audit
from trueup.sweep import by_scenario, new_run_id, summary_line

DISCOVER = "discover"


def audit(
    root: Path,
    library: str,
    script: Path,
    *,
    ensure: Callable[[Path, str], Path] = venvs.ensure,
    run: Callable[..., dict[str, Any]] = run_audit,
    out: Callable[[str], None] = print,
) -> tuple[Path, list[dict[str, Any]]]:
    run_id = new_run_id(library).replace(f"-{library}", f"-audit-{library}")
    run_dir = root / ".trueup" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    if not script.is_file():
        results.append(not_run(DISCOVER, library, f"no such file: {script}"))
    else:
        try:
            out(f"preparing venv for {library}")
            python = ensure(root, library)
        except Exception as e:  # noqa: BLE001 - reported as could not run
            python = None
            results.append(not_run(DISCOVER, library, f"venv not ready: {e}"))
        if python is not None:
            results = _audit_runs(python, library, script, run, out)
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
        f"trueup audit {script} --library {library}  run {run_id}",
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
    return run_dir, results


def _audit_runs(python: Path, library: str, script: Path, run: Callable[..., dict[str, Any]],
                out: Callable[[str], None]) -> list[dict[str, Any]]:
    first = run(python, library, script, DISCOVER, {})
    out(summary_line(first))
    if first["status"] != RAN:
        return [first]
    routes = sorted({e["path"] for e in first["observation"]["truth"]["fake_log"]} & set(SCENARIOS_BY_ROUTE))
    if not routes:
        return [not_run(DISCOVER, library, "main() made no provider call through the fake "
                        "(check that its clients use OPENAI_BASE_URL / ANTHROPIC_BASE_URL)")]
    out(f"main() calls: {', '.join(routes)}")
    results = []
    for route in routes:
        for scenario in SCENARIOS_BY_ROUTE[route]:
            r = run(python, library, script, scenario, {route: scenario})
            if r["status"] == RAN:
                r["mismatches"] = [m.to_dict() for m in compare(Observation.from_dict(r["observation"]))]
            out(summary_line(r))
            results.append(r)
    return results
