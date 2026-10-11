"""Trueup traces itself with neatlogs.

One trueup run = one neatlogs session (session id = run id). Each worker runs as
its own root trace named after it (trueup-planner, trueup-runner, ...), with
trueup.run_id, trueup.library and, where it applies, trueup.verdict.

This is the outer trace only. Scenario runs happen in subprocesses whose env
drops NEATLOGS_API_KEY and sets NEATLOGS_DISABLE_EXPORT / OTEL_*_EXPORTER=none
(trueup.runner.setups), so their spans never leave the machine.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import sys
from typing import Any, Callable, Iterator

from trueup import __version__

KEY_VAR = "NEATLOGS_API_KEY"
WORKERS = ("trueup-planner", "trueup-runner", "trueup-comparer", "trueup-checker", "trueup-deduper",
           "trueup-fixer", "trueup-verifier", "trueup-reporter")

_state: dict[str, Any] = {"active": False, "run_id": None, "library": None, "flushed": False, "closed": False,
                         "variant": None, "opened": [], "delivery": "not configured"}


def active() -> bool:
    return bool(_state["active"])


def session_id() -> str | None:
    return _state["run_id"] if active() else None


def opened() -> list[dict[str, Any]]:
    """The worker traces this run opened, to compare with what neatlogs received."""
    return list(_state["opened"])


def delivery() -> str:
    """Last export state: not configured, pending, delivered, or failed."""
    return str(_state["delivery"])


def start(run_id: str, library: str, command: str, out: Callable[[str], None] = print,
          init: Callable[..., Any] | None = None, variant: str | None = None,
          pii_enabled: bool = False) -> bool:
    """Start one Neatlogs session for a Trueup command. Returns whether tracing is on.

    variant (v1/v2) goes into the tags. With v2 every worker trace is flushed when it ends: of the
    traces v1's fix and plan runs opened, neatlogs holds 9 (session 20261010T235208Z-plan-neatlogs has
    none), and v1 flushed only once at exit."""
    _state.update(active=False, run_id=run_id, library=library, flushed=False, closed=False, variant=variant,
                  opened=[], delivery="not configured")
    if not os.environ.get(KEY_VAR):
        out(f"{KEY_VAR} is not set: running without neatlogs tracing")
        return False
    if init is None:
        import neatlogs

        init = neatlogs.init
    try:
        # Trueup has no end users; the team name fills neatlogs' user column (TRUEUP_USER overrides it).
        init(api_key=os.environ[KEY_VAR], workflow_name="trueup", instrumentations=["openai"],
             pii_enabled=pii_enabled,
             user_id=os.environ.get("TRUEUP_USER", "jenny-builds"),
             tags=[f"run_id:{run_id}", f"library:{library}", f"trueup:{__version__}", f"command:{command}"]
             + ([f"variant:{variant}"] if variant else []))
    except Exception as e:  # noqa: BLE001 - tracing must not stop the run
        out(f"neatlogs init failed ({type(e).__name__}): running without neatlogs tracing")
        return False
    _state["active"] = True
    _state["delivery"] = "pending"
    atexit.register(shutdown)
    out(f"neatlogs tracing on, session {run_id}")
    return True


def flush() -> bool:
    """Flush Neatlogs once and report whether delivery was confirmed."""
    if not active() or _state["flushed"]:
        return _state["delivery"] in ("not configured", "delivered")
    _state["flushed"] = True
    try:
        import neatlogs

        ok = neatlogs.flush()
        # Current neatlogs returns bool. Treat None as success for older compatible SDKs.
        delivered = ok is not False
        _state["delivery"] = "delivered" if delivered else "failed"
        if not delivered:
            print("neatlogs flush did not confirm trace delivery", file=sys.stderr)
        return delivered
    except Exception as e:  # noqa: BLE001
        _state["delivery"] = "failed"
        print(f"neatlogs flush failed ({type(e).__name__})", file=sys.stderr)
        return False


def shutdown() -> bool:
    """Flush pending spans and close the Neatlogs exporter exactly once."""
    if not active() or _state["closed"]:
        return _state["delivery"] in ("not configured", "delivered")
    delivered = flush()
    _state["closed"] = True
    try:
        import neatlogs

        neatlogs.shutdown()
    except Exception as e:  # noqa: BLE001 - tracing must not stop the run
        _state["delivery"] = "failed"
        print(f"neatlogs shutdown failed ({type(e).__name__})", file=sys.stderr)
        return False
    _state["active"] = False
    return delivered


@contextlib.contextmanager
def worker(name: str, **attrs: Any) -> Iterator[Any]:
    """A root trace for one worker in the run's session. Yields a span (or None when off)."""
    if name not in WORKERS:
        raise ValueError(f"unknown worker {name!r}")
    _state["opened"].append({"name": name, **{k: str(v) for k, v in attrs.items()}})
    if not active():
        yield None
        return
    import neatlogs

    a = {"trueup.run_id": _state["run_id"], "trueup.library": _state["library"], "neatlogs.workflow.name": name,
         **({"trueup.variant": _state["variant"]} if _state["variant"] else {}),
         **{f"trueup.{k}": v for k, v in attrs.items()}}
    # Use the span trace() yields: neatlogs keeps its own context, so OTel's current span can be another one.
    with neatlogs.trace(name=name, kind="AGENT", session_id=_state["run_id"], **a) as span:
        # neatlogs' exporter reads output.value and metadata (OpenInference names); trueup.* alone never shows.
        if span is not None:
            labels = {k: str(v) for k, v in a.items() if k.startswith("trueup.")}
            span.set_attribute("metadata", json.dumps(labels))
        yield span
    if _state["variant"] == "v2":
        try:
            if neatlogs.flush() is False:
                _state["delivery"] = "failed"
                print("neatlogs worker flush did not confirm trace delivery", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            _state["delivery"] = "failed"
            print(f"neatlogs flush failed ({type(e).__name__})", file=sys.stderr)


def mark(name: str, **attrs: Any) -> None:
    """A child step named after an event (e.g. "lead withdrawn"). neatlogs detections match span names reliably,
    not the output text of an agent span, so events a detection must see get their own named step."""
    if not active():
        return
    import neatlogs

    try:
        with neatlogs.trace(name=name, kind="TOOL", **{f"trueup.{k}": str(v) for k, v in attrs.items()}) as span:
            if span is not None and attrs:
                span.set_attribute("output.value", json.dumps({k: str(v) for k, v in attrs.items()}))
    except Exception as e:  # noqa: BLE001 - tracing must not stop the run
        print(f"neatlogs mark failed ({type(e).__name__})", file=sys.stderr)


def set_verdict(span: Any, verdict: str) -> None:
    if span is not None:
        span.set_attribute("trueup.verdict", verdict)
        # The verdict is the worker's output in neatlogs, so it shows in the trace list and detections see it.
        span.set_attribute("neatlogs.agent.output", verdict)
        span.set_attribute("output.value", verdict)
        meta = json.loads((getattr(span, "attributes", None) or {}).get("metadata") or "{}")
        span.set_attribute("metadata", json.dumps({**meta, "trueup.verdict": verdict}))


def run_traced(run_id: str, library: str, command: str, body: Callable[[], int],
               out: Callable[[str], None] = print, variant: str | None = None,
               pii_enabled: bool = False) -> int:
    """Start tracing, then flush and shut down on the way out, also when it raises."""
    start(run_id, library, command, out, variant=variant, pii_enabled=pii_enabled)
    try:
        return body()
    finally:
        shutdown()
