"""Group checked leads that share a cause: same library, same check, same code path. Pure.

The code path is the framework for framework scenarios, else the provider API and
whether the app streamed. The trace's shape is part of the key, so "span is OK"
and "span is ERROR without an exception event" stay apart.
"""

from __future__ import annotations

import re
from typing import Any

from trueup.core.model import Finding, Severity

_INDEX = re.compile(r"^(call \d+ |tool run \d+ \([^)]*\) )")


def field_kind(field: str) -> str:
    return _INDEX.sub("", field)


def code_path(scenario: dict[str, Any]) -> str:
    if scenario.get("framework", "none") != "none":
        return scenario["framework"]
    mode = "stream" if "stream" in scenario.get("app", "") else "create"
    return f"{scenario.get('provider')} {scenario.get('api')} {mode}"


def trace_shape(lead: dict[str, Any]) -> str:
    trace = lead["trace"]
    if lead["check"] in ("run_status", "call_status") and isinstance(trace, str):
        return trace
    return "missing" if trace in (None, "no span", "no span records an error") else "wrong"


def key(item: dict[str, Any]) -> tuple[str, ...]:
    lead = item["lead"]
    return (lead["library"], lead["check"], field_kind(lead["field"]), code_path(item["scenario"]), trace_shape(lead))


def group(items: list[dict[str, Any]]) -> list[Finding]:
    """items: {lead, scenario, rules, decided_by}. One Finding per key, in first-seen order."""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    out = []
    for (library, check, kind, path, shape), its in groups.items():
        scenarios = sorted({it["lead"]["scenario"] for it in its})
        severity = max(Severity(it["lead"]["severity"]) for it in its)
        sample = its[0]["lead"]
        if shape == "missing":
            says = "not recorded"
        elif check.endswith("status"):
            says = f"is {shape}"
        else:
            says = "recorded wrong"
        caveats = sorted({it["decided_by"]["reason"] for it in its if it.get("decided_by")})
        out.append(Finding(
            id=f"{library}-{check}-{_slug(path)}-{_slug(kind)}-{_slug(shape)}",
            title=f"{library}, {path}: {kind} {says}",
            library=library,
            severity=severity,
            run_ids=tuple(scenarios),
            cause=None,
            details={
                "check": check,
                "field": kind,
                "code_path": path,
                "trace": shape,
                "scenarios": scenarios,
                "example": {"scenario": sample["scenario"], "field": sample["field"], "truth": sample["truth"],
                            "trace": sample["trace"]},
                "rules": {r["rule"]: r["reason"] for r in its[0]["rules"]},
                "caveats": caveats,
                "leads": [it["lead"] for it in its],
            },
        ))
    return sorted(out, key=lambda f: (-f.severity.rank, f.id))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
