"""trueup sweep <library>: run the plain-SDK scenarios against one library."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trueup.core import report
from trueup.core.compare import compare, leads
from trueup.core.model import Mismatch, Observation
from trueup.runner import NOT_RUN, RAN, run_scenario, venvs
from trueup.runner.run import not_run
from trueup.scenarios import plain_sdk


def new_run_id(library: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{library}"


def summary_line(r: dict[str, Any]) -> str:
    sid = r["scenario"]
    if r["status"] != RAN:
        return f"{sid:30} NOT RUN  {r['reason']}"
    t, tr = r["observation"]["truth"], r["observation"]["trace"]
    app = t["app"]["outcome"] if t["outcome"] == "ok" else f"raised {t['exception']}"
    spans = ", ".join(f"{s['name']}={s['status']['code']}" for s in tr["spans"]) or "none"
    line = f"{sid:30} ran {r['seconds']:5.1f}s  app {app}; fake calls {t['calls']}; spans {len(tr['spans'])}: {spans}"
    if t.get("expected_mismatch"):
        line += f"  [truth differs from scenario expectation: {', '.join(t['expected_mismatch'])}]"
    return line


def sweep(
    root: Path,
    library: str,
    *,
    ensure: Callable[[Path, str], Path] = venvs.ensure,
    run: Callable[..., dict[str, Any]] = run_scenario,
    out: Callable[[str], None] = print,
) -> tuple[Path, list[dict[str, Any]]]:
    run_id = new_run_id(library)
    run_dir = root / ".trueup" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    scenarios = plain_sdk()
    try:
        out(f"preparing venv for {library}")
        python: Path | None = ensure(root, library)
        venv_error = None
    except Exception as e:  # noqa: BLE001 - every scenario is reported NOT RUN
        python, venv_error = None, f"venv not ready: {e}"
    results = []
    for s in scenarios:
        r = not_run(s.id, library, venv_error) if python is None else run(python, library, s.id)
        if r["status"] == RAN:
            r["mismatches"] = [m.to_dict() for m in compare(Observation.from_dict(r["observation"]))]
        results.append(r)
        out(summary_line(r))
        (run_dir / f"{s.id}.json").write_text(json.dumps(r, indent=1, default=str))
    ran = sum(r["status"] == RAN for r in results)
    by = by_scenario(results)
    c = report.counts(by)
    table = report.table(by)
    totals = (f"leads: {c['leads']} (high {c['by_severity']['high']}, medium {c['by_severity']['medium']}, "
              f"low {c['by_severity']['low']})  notes: {c['notes']}")
    lines = [
        f"trueup sweep {library}  run {run_id}",
        f"scenarios: {len(results)}  ran: {ran}  not run: {len(results) - ran}  "
        f"time: {time.monotonic() - started:.0f} s",
        totals,
        "A lead is a disagreement between truth and trace, not a confirmed bug.",
        "",
        *(summary_line(r) for r in results),
        "",
        table,
    ]
    (run_dir / "summary.txt").write_text("\n".join(lines) + "\n")
    (run_dir / "index.json").write_text(json.dumps({
        "run_id": run_id,
        "library": library,
        "scenarios": [{"id": r["scenario"], "status": r["status"], "reason": r["reason"]} for r in results],
    }, indent=1))
    not_run_list = [{"scenario": r["scenario"], "reason": r["reason"]} for r in results if r["status"] != RAN]
    (run_dir / "leads.json").write_text(json.dumps(report.leads_payload(run_id, library, by, not_run_list), indent=1,
                                                   default=str))
    out("")
    out(table)
    out(totals)
    out(f"ran {ran}/{len(results)}; wrote {run_dir}")
    return run_dir, results


def by_scenario(results: list[dict[str, Any]]) -> list[tuple[str, list[Mismatch]]]:
    return [(r["scenario"], [Mismatch.from_dict(m) for m in r.get("mismatches", [])])
            for r in results if r["status"] == RAN]


def exit_code(results: list[dict[str, Any]]) -> int:
    """1 if any lead, else 2 if any scenario could not run, else 0."""
    if any(leads([m for _, ms in by_scenario(results) for m in ms])):
        return 1
    return 2 if not results or any(r["status"] == NOT_RUN for r in results) else 0
