"""Parent side: run one scenario in a fresh subprocess and read its observation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from trueup.runner.setups import CHILD_ENV, CHILD_ENV_DROP
from trueup.runner import truth
from trueup.scenarios import BUILT, get

SRC = Path(__file__).resolve().parents[2]  # .../src
RAN = "ran"
NOT_RUN = "not_run"


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for k in CHILD_ENV_DROP:
        env.pop(k, None)
    env.update(CHILD_ENV)
    env["PYTHONPATH"] = str(SRC)
    env.pop("VIRTUAL_ENV", None)
    return env


def not_run(scenario_id: str, library: str, reason: str, seconds: float = 0.0, detail: str | None = None) -> dict[str, Any]:
    return {"scenario": scenario_id, "library": library, "status": NOT_RUN, "reason": reason,
            "detail": detail, "seconds": round(seconds, 3), "observation": None}


def _last_line(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1].strip() if lines else "no output"


def run_scenario(python: Path, library: str, scenario_id: str, timeout: float = 90) -> dict[str, Any]:
    """Returns {scenario, library, status, reason, seconds, observation}."""
    try:
        scenario = get(scenario_id)
    except KeyError as e:
        return not_run(scenario_id, library, str(e))
    if scenario.status != BUILT:
        return not_run(scenario_id, library, f"scenario is {scenario.status}")
    return _run_child(python, library, scenario_id, [library, scenario_id], timeout)


def run_audit(python: Path, library: str, script: Path, label: str, overrides: dict[str, str],
              timeout: float = 90) -> dict[str, Any]:
    """Run a user's script's main() with the fake answering as `overrides` say. Same shape as run_scenario."""
    with tempfile.TemporaryDirectory(prefix="trueup-") as tmp:
        ov = Path(tmp) / "overrides.json"
        ov.write_text(json.dumps(overrides))
        return _run_child(python, library, label, ["--audit", library, str(script.resolve()), str(ov)], timeout)


def _run_child(python: Path, library: str, label: str, args: list[str], timeout: float,
               env: dict[str, str] | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trueup-") as tmp:
        out = Path(tmp) / "obs.json"
        cmd = [str(python), "-m", "trueup.runner.child", *args, str(out)]
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, env=env or child_env(), cwd=tmp, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return not_run(label, library, f"timed out after {timeout:.0f} s", time.monotonic() - t0)
        except OSError as e:
            return not_run(label, library, f"could not start {python}: {e}")
        seconds = time.monotonic() - t0
        if not out.exists():
            tail = (p.stderr or p.stdout).strip()[-2000:]
            return not_run(label, library, f"child exited {p.returncode} without output: {_last_line(tail)}",
                           seconds, detail=tail)
        payload = json.loads(out.read_text())
    if not payload["ok"]:
        return not_run(label, library, "setup or harness error: " + _last_line(payload["error"]), seconds,
                       detail=payload["error"])
    return {"scenario": label, "library": library, "status": RAN, "reason": None,
            "seconds": round(seconds, 3), "observation": payload["observation"]}


def run_record_audit(python: Path, library: str, script: Path, provider: str, base_url: str,
                     recording: Path, timeout: float = 180) -> dict[str, Any]:
    """Run one explicitly opted-in real-provider audit through RecordingProxy."""
    from trueup.recording import read_recordings, truth_log

    key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_name):
        return not_run("record", library, f"{key_name} is not set")
    env = child_env()
    env[key_name] = os.environ[key_name]
    if provider == "openai":
        env["OPENAI_BASE_URL"] = base_url.rstrip("/") + "/v1"
    else:
        env["ANTHROPIC_BASE_URL"] = base_url.rstrip("/")
    result = _run_child(python, library, "record", ["--record-audit", library, str(script.resolve())], timeout, env)
    if result["status"] == RAN:
        log = truth_log(read_recordings(recording))
        app = result["observation"].pop("app")
        result["observation"]["truth"] = {**truth.derive(log, app), "app": app,
                                             "recording": str(recording), "fake_log": log,
                                             "source": "recording_proxy"}
    return result
