"""Explicitly export a small set of fake-provider regression scenarios."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trueup.runner import RAN, run_scenario, venvs

CASES = {
    "neatlogs": ("oa-resp-stream-error-event", "an-stream-helper", "ag-llm-fails"),
    "openinference": ("oa-resp-stream-error-event", "an-stream-helper", "ag-llm-fails"),
    "openllmetry": ("oa-resp-stream-error-event", "an-stream-helper", "ag-llm-fails"),
}
MAX_SPANS = 30


def demo_export(root: Path, library: str, *, approved: bool,
                ensure: Callable[[Path, str], Path] = venvs.ensure,
                run: Callable[..., dict[str, Any]] = run_scenario,
                out: Callable[[str], None] = print) -> dict[str, Any]:
    if not approved:
        raise ValueError("refusing export without --yes-export-fake-traces")
    cases = CASES[library]
    python = ensure(root, library)
    counted = [run(python, library, case) for case in cases]
    failed = [r for r in counted if r["status"] != RAN]
    if failed:
        raise RuntimeError("demo count did not run: " + "; ".join(
            f"{r['scenario']}: {r['reason']}" for r in failed))
    planned_spans = sum(len(r["observation"]["trace"]["spans"]) for r in counted)
    out(f"counted first: {len(cases)} scenarios, {planned_spans} spans (fake provider only; cap {MAX_SPANS})")
    if planned_spans > MAX_SPANS:
        raise RuntimeError(f"span cap exceeded before export: {planned_spans} > {MAX_SPANS}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"demo-{library}-{stamp}"
    results = [run(python, library, case, export_session=session_id) for case in cases]
    failed = [r for r in results if r["status"] != RAN]
    if failed:
        raise RuntimeError("demo scenario did not run: " + "; ".join(
            f"{r['scenario']}: {r['reason']}" for r in failed))
    exported_spans = sum(len(r["observation"]["trace"]["spans"]) for r in results)
    if exported_spans > MAX_SPANS:
        raise RuntimeError(f"span cap exceeded: {exported_spans} > {MAX_SPANS}")
    return {"library": library, "session_id": session_id, "scenarios": list(cases),
            "counted_spans": planned_spans, "spans": exported_spans}
