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
import os
import sys
from typing import Any, Callable, Iterator

from trueup import __version__

KEY_VAR = "NEATLOGS_API_KEY"
WORKERS = ("trueup-planner", "trueup-runner", "trueup-comparer", "trueup-checker", "trueup-deduper")

_state: dict[str, Any] = {"active": False, "run_id": None, "library": None, "flushed": False}


def active() -> bool:
    return bool(_state["active"])


def session_id() -> str | None:
    return _state["run_id"] if active() else None


def start(run_id: str, library: str, command: str, out: Callable[[str], None] = print,
          init: Callable[..., Any] | None = None) -> bool:
    """neatlogs.init for a command that calls the model. Returns whether tracing is on."""
    _state.update(active=False, run_id=run_id, library=library, flushed=False)
    if not os.environ.get(KEY_VAR):
        out(f"{KEY_VAR} is not set: running without neatlogs tracing")
        return False
    if init is None:
        import neatlogs

        init = neatlogs.init
    try:
        init(api_key=os.environ[KEY_VAR], workflow_name="trueup", instrumentations=["openai"],
             tags=[f"run_id:{run_id}", f"library:{library}", f"trueup:{__version__}", f"command:{command}"])
    except Exception as e:  # noqa: BLE001 - tracing must not stop the run
        out(f"neatlogs init failed ({type(e).__name__}): running without neatlogs tracing")
        return False
    _state["active"] = True
    atexit.register(flush)
    out(f"neatlogs tracing on, session {run_id}")
    return True


def flush() -> None:
    """Flush neatlogs once. Safe to call more than once and when tracing is off."""
    if not active() or _state["flushed"]:
        return
    _state["flushed"] = True
    try:
        import neatlogs

        neatlogs.flush()
    except Exception as e:  # noqa: BLE001
        print(f"neatlogs flush failed ({type(e).__name__})", file=sys.stderr)


@contextlib.contextmanager
def worker(name: str, **attrs: Any) -> Iterator[Any]:
    """A root trace for one worker in the run's session. Yields a span (or None when off)."""
    if name not in WORKERS:
        raise ValueError(f"unknown worker {name!r}")
    if not active():
        yield None
        return
    import neatlogs

    a = {"trueup.run_id": _state["run_id"], "trueup.library": _state["library"], "neatlogs.workflow.name": name,
         **{f"trueup.{k}": v for k, v in attrs.items()}}
    with neatlogs.trace(name=name, kind="AGENT", session_id=_state["run_id"], **a):
        from opentelemetry import trace as otel

        yield otel.get_current_span()


def set_verdict(span: Any, verdict: str) -> None:
    if span is not None:
        span.set_attribute("trueup.verdict", verdict)


def run_traced(run_id: str, library: str, command: str, body: Callable[[], int],
               out: Callable[[str], None] = print) -> int:
    """Start tracing, run the command, and flush on the way out, also when it raises."""
    start(run_id, library, command, out)
    try:
        return body()
    finally:
        flush()
