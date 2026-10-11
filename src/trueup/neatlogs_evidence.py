"""Pull reviewable Neatlogs evidence through its read-only MCP tools."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from trueup.neatlogs_read import Reader


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n")


def pull(root: Path, reader: Reader | None = None, out: Callable[[str], None] = print) -> Path:
    """Pull detections, trends, analytics and Neatlogs fix suggestions without mutating the project."""
    reader = reader or Reader()
    target = root / ".trueup" / "neatlogs"
    detections = reader.call("list_detections")
    items = detections.get("detections", detections.get("results", [])) if isinstance(detections, dict) else []
    trends = []
    for item in items:
        name = item.get("display_name") or item.get("name")
        if name:
            trends.append({"detection_name": name,
                           "trend": reader.call("get_detection_trend", detection_name=name, period="30d",
                                                granularity="day")})
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=14)
    analytics = {}
    for view in ("kpis", "cost", "errors", "time", "detections", "workflows"):
        analytics[view] = reader.call("get_project_analytics", **{
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"), "view": view,
        })
    triage = {}
    for status in ("draft", "open", "in_progress", "resolved", "archived"):
        triage[status] = reader.call("triage_list", status=status)
    _write(target / "detections.json", {"source": "Neatlogs MCP", "detections": detections, "trends": trends})
    _write(target / "analytics.json", {"source": "Neatlogs MCP", "window": {"from": start, "to": now},
                                        "views": analytics})
    _write(target / "fix-suggestions.json", {"source": "Neatlogs MCP", "by_status": triage})
    out(f"wrote read-only Neatlogs evidence to {target}")
    return target
