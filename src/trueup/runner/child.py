"""Runs one scenario under one library. Executed in a fresh subprocess.

python -m trueup.runner.child <library> <scenario_id> <out.json>
"""

from __future__ import annotations

import gc
import json
import logging
import sys
import time
import traceback
from importlib import metadata
from typing import Any

from trueup.fake import FakeProvider
from trueup.runner import truth
from trueup.runner.apps import APPS
from trueup.runner.setups import SETUPS, VERSIONED
from trueup.scenarios import get

ATTR_MAX = 2000


def _value(v: Any) -> Any:
    if isinstance(v, (tuple, list)):
        return [_value(x) for x in v]
    if isinstance(v, str) and len(v) > ATTR_MAX:
        return v[:ATTR_MAX] + f"...[{len(v) - ATTR_MAX} more chars]"
    return v


def span_to_dict(s: Any) -> dict[str, Any]:
    ctx = s.get_span_context()
    return {
        "name": s.name,
        "kind": s.kind.name,
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_id": format(s.parent.span_id, "016x") if s.parent else None,
        "start_ns": s.start_time,
        "end_ns": s.end_time,
        "status": {"code": s.status.status_code.name, "description": s.status.description},
        "scope": s.instrumentation_scope.name if s.instrumentation_scope else None,
        "attributes": {k: _value(v) for k, v in (s.attributes or {}).items()},
        "events": [{"name": e.name, "attributes": {k: _value(v) for k, v in (e.attributes or {}).items()}} for e in s.events],
    }


def _versions(library: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for dist in VERSIONED[library]:
        try:
            out[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[dist] = None
    return out


def run(library: str, scenario_id: str) -> dict[str, Any]:
    scenario = get(scenario_id)
    logging.disable(logging.CRITICAL)
    exporter, flush = SETUPS[library]()
    app_fn = APPS[scenario.app]
    with FakeProvider() as fake:
        t0 = time.monotonic()
        try:
            result = app_fn(fake.base_url, scenario.model)
            app = {"outcome": "ok", "result": result}
        except BaseException as e:  # noqa: BLE001 - the outcome is the data
            app = {
                "outcome": "exception",
                "exception_type": type(e).__name__,
                "exception_module": type(e).__module__,
                "message": str(e)[:500],
            }
        app["seconds"] = round(time.monotonic() - t0, 3)
        # Let streams closed by garbage collection end their spans.
        gc.collect()
        flush()
        fake_log = fake.log.entries()
    spans = [span_to_dict(s) for s in exporter.get_finished_spans()]
    t = truth.derive(fake_log, app)
    return {
        "truth": {
            **t,
            "scenario": scenario_id,
            "expected": scenario.expected,
            "expected_mismatch": truth.check_expected(scenario.expected, t),
            "app": app,
            "fake_log": fake_log,
        },
        "trace": {"library": library, "versions": _versions(library), "spans": spans},
    }


def main(argv: list[str]) -> int:
    library, scenario_id, out_path = argv
    try:
        payload = {"ok": True, "observation": run(library, scenario_id)}
    except BaseException:  # noqa: BLE001 - reported as NOT RUN by the parent
        payload = {"ok": False, "error": traceback.format_exc(limit=8)}
    with open(out_path, "w") as f:
        json.dump(payload, f, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
