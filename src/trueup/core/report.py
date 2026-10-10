"""Leads table and leads.json payload. Pure: returns strings and dicts."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from trueup.core.model import Mismatch, Severity

COLUMNS = ("scenario", "check", "expected", "actual", "severity")
CELL_MAX = 48


def _cell(v: Any) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= CELL_MAX else s[: CELL_MAX - 3] + "..."


def rows(by_scenario: list[tuple[str, list[Mismatch]]]) -> list[tuple[str, ...]]:
    out = []
    for sid, ms in by_scenario:
        for m in sorted(ms, key=lambda m: -m.severity.rank):
            check = m.check if m.kind == "lead" else f"{m.check} (note)"
            out.append((sid, check, _cell(m.truth), _cell(m.trace), m.severity.value.upper()))
    return out


def table(by_scenario: list[tuple[str, list[Mismatch]]]) -> str:
    body = rows(by_scenario)
    if not body:
        return "no leads"
    widths = [max(len(r[i]) for r in [COLUMNS, *body]) for i in range(len(COLUMNS))]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    return "\n".join([line(COLUMNS), line(tuple("-" * w for w in widths)), *(line(r) for r in body)])


def counts(by_scenario: list[tuple[str, list[Mismatch]]]) -> dict[str, Any]:
    leads = [m for _, ms in by_scenario for m in ms if m.kind == "lead"]
    notes = [m for _, ms in by_scenario for m in ms if m.kind == "note"]
    sev = Counter(m.severity.value for m in leads)
    return {
        "leads": len(leads),
        "notes": len(notes),
        "by_severity": {s.value: sev.get(s.value, 0) for s in sorted(Severity, reverse=True)},
        "by_check": dict(sorted(Counter(m.check for m in leads).items())),
        "scenarios_with_leads": sum(any(m.kind == "lead" for m in ms) for _, ms in by_scenario),
    }


def leads_payload(run_id: str, library: str, by_scenario: list[tuple[str, list[Mismatch]]],
                  not_run: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "library": library,
        "note": "A lead is a disagreement between truth and trace. It is not a confirmed bug.",
        "counts": counts(by_scenario),
        "not_run": not_run,
        "scenarios": [{"scenario": sid, "mismatches": [m.to_dict() for m in ms]} for sid, ms in by_scenario],
    }
