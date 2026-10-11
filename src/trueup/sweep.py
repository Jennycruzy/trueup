"""trueup sweep <library> [--framework ...]: run the scenarios against one library."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trueup import tracing
from trueup.core import report
from trueup.core.compare import compare, leads
from trueup.core.model import Mismatch, Observation
from trueup.runner import NOT_RUN, RAN, run_scenario, venvs
from trueup.runner.run import not_run
from trueup.scenarios import FRAMEWORKS, select
from trueup.scenarios.proposed import load as load_proposed
from trueup.state import State


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
    framework: str = "all",
    *,
    proposed: str | None = None,
    cases: list[str] | None = None,
    ensure: Callable[[Path, str], Path] = venvs.ensure,
    run: Callable[..., dict[str, Any]] = run_scenario,
    out: Callable[[str], None] = print,
    run_id: str | None = None,
    providers: tuple[str, ...] | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    run_id = run_id or new_run_id(library) + ("-proposed" if proposed else "")
    run_dir = root / ".trueup" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    scenarios = select(framework) if proposed is None else [
        s for s in load_proposed(proposed) if framework == "all" or s.framework in FRAMEWORKS[framework]]
    if cases:
        from trueup.scenarios import get

        scenarios = [get(c) for c in cases]  # KeyError for an unknown id
    if providers:
        unknown = set(providers) - {"openai", "anthropic"}
        if unknown:
            raise ValueError(f"unknown provider(s): {', '.join(sorted(unknown))}")
        scenarios = [s for s in scenarios if s.provider in providers]
    with State(root) as state:
        state.begin_run(run_id, "sweep", library)
        cached = {s.id: state.observation(run_id, s.id) for s in scenarios}
        pending = [s for s in scenarios if cached[s.id] is None]
        python: Path | None = None
        venv_error = None
        if pending:
            try:
                out(f"preparing venv for {library}")
                python = ensure(root, library)
            except Exception as e:  # noqa: BLE001 - every pending scenario is reported NOT RUN
                venv_error = f"venv not ready: {e}"
        results = []
        with tracing.worker("trueup-runner") as span:
            for s in scenarios:
                r = cached[s.id]
                if r is None:
                    r = not_run(s.id, library, venv_error) if python is None else run(python, library, s.id)
                    state.save_observation(run_id, s.id, r)
                else:
                    out(f"{s.id:30} resumed from state.db")
                results.append(r)
                out(summary_line(r))
            tracing.set_verdict(span, f"ran {sum(r['status'] == RAN for r in results)}/{len(results)}")
    with tracing.worker("trueup-comparer") as span:
        for r in results:
            if r["status"] == RAN:
                r["mismatches"] = [m.to_dict() for m in compare(Observation.from_dict(r["observation"]))]
            (run_dir / f"{r['scenario']}.json").write_text(json.dumps(r, indent=1, default=str))
        n = sum(len(leads([Mismatch.from_dict(m) for m in r.get("mismatches", [])])) for r in results)
        tracing.set_verdict(span, f"{n} leads")
    ran = sum(r["status"] == RAN for r in results)
    by = by_scenario(results)
    c = report.counts(by)
    table = report.table(by)
    totals = (f"leads: {c['leads']} (high {c['by_severity']['high']}, medium {c['by_severity']['medium']}, "
              f"low {c['by_severity']['low']})  notes: {c['notes']}")
    lines = [
        f"trueup sweep {library} --framework {framework}"
        f"{f' --provider {','.join(providers)}' if providers else ''}"
        f"{f' --proposed {proposed}' if proposed else ''}  run {run_id}",
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
        "framework": framework,
        "providers": list(providers or ("openai", "anthropic")),
        "proposed": proposed,
        "scenarios": [{"id": r["scenario"], "status": r["status"], "reason": r["reason"]} for r in results],
    }, indent=1))
    not_run_list = [{"scenario": r["scenario"], "reason": r["reason"]} for r in results if r["status"] != RAN]
    (run_dir / "leads.json").write_text(json.dumps(report.leads_payload(run_id, library, by, not_run_list), indent=1,
                                                   default=str))
    out("")
    out(table)
    out(totals)
    out(f"ran {ran}/{len(results)}; wrote {run_dir}")
    with State(root) as state:
        state.finish_run(run_id, "mismatch" if exit_code(results) == 1 else "complete" if exit_code(results) == 0
                         else "error")
    return run_dir, results


def by_scenario(results: list[dict[str, Any]]) -> list[tuple[str, list[Mismatch]]]:
    return [(r["scenario"], [Mismatch.from_dict(m) for m in r.get("mismatches", [])])
            for r in results if r["status"] == RAN]


def exit_code(results: list[dict[str, Any]]) -> int:
    """1 if any lead, else 2 if any scenario could not run, else 0."""
    if any(leads([m for _, ms in by_scenario(results) for m in ms])):
        return 1
    return 2 if not results or any(r["status"] == NOT_RUN for r in results) else 0
