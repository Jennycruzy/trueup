"""Runner and sweep, offline. Subprocess runs against real venvs are in test_e2e.py."""

import json
import sys
from pathlib import Path

import pytest

from trueup.cli import EXIT_ERROR, EXIT_OK
from trueup.runner import NOT_RUN, RAN, run_scenario
from trueup.runner.run import SRC, child_env
from trueup.scenarios import plain_sdk
from trueup.sweep import exit_code, summary_line, sweep


def test_child_env_points_at_source_tree():
    env = child_env({})
    assert env["PYTHONPATH"] == str(SRC)
    assert (Path(env["PYTHONPATH"]) / "trueup" / "runner" / "child.py").exists()


def test_not_built_scenario_is_not_run_with_reason():
    r = run_scenario(Path(sys.executable), "neatlogs", "lg-agent")
    assert r["status"] == NOT_RUN and "not_built" in r["reason"]


def test_unknown_scenario_is_not_run():
    r = run_scenario(Path(sys.executable), "neatlogs", "nope")
    assert r["status"] == NOT_RUN and "unknown scenario" in r["reason"]


def test_missing_python_is_not_run():
    r = run_scenario(Path("/nonexistent/python"), "neatlogs", "oa-chat-plain")
    assert r["status"] == NOT_RUN and "could not start" in r["reason"]


@pytest.mark.e2e  # spawns a subprocess
def test_library_import_failure_is_not_run(tmp_path):
    # This interpreter has no neatlogs, so setup fails inside the child.
    r = run_scenario(Path(sys.executable), "neatlogs", "oa-chat-plain", timeout=60)
    assert r["status"] == NOT_RUN
    assert "neatlogs" in r["reason"]


@pytest.mark.e2e  # spawns a subprocess
def test_child_crash_without_output_is_not_run(tmp_path):
    bad = tmp_path / "python"
    bad.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
    bad.chmod(0o755)
    r = run_scenario(bad, "neatlogs", "oa-chat-plain")
    assert r["status"] == NOT_RUN and "exited 3" in r["reason"] and "boom" in r["reason"]


def _fake_obs(sid):
    return {
        "scenario": sid, "library": "x", "status": RAN, "reason": None, "seconds": 1.0,
        "observation": {
            "truth": {"calls": 1, "outcome": "ok", "app": {"outcome": "ok"}, "expected_mismatch": []},
            "trace": {"spans": [{"name": "chat", "status": {"code": "OK"}}]},
        },
    }


def test_sweep_writes_one_file_per_scenario_and_summary(tmp_path):
    run_dir, results = sweep(
        tmp_path, "openinference",
        ensure=lambda root, lib: Path("/py"),
        run=lambda py, lib, sid: _fake_obs(sid),
        out=lambda s: None,
    )
    ids = [s.id for s in plain_sdk()]
    assert [r["scenario"] for r in results] == ids
    assert run_dir.parent == tmp_path / ".trueup" / "runs"
    for sid in ids:
        assert json.loads((run_dir / f"{sid}.json").read_text())["status"] == RAN
    summary = (run_dir / "summary.txt").read_text()
    assert f"ran: {len(ids)}" in summary and "not run: 0" in summary
    assert exit_code(results) == EXIT_OK


def test_sweep_venv_failure_reports_every_scenario_not_run(tmp_path):
    def broken(root, lib):
        raise RuntimeError("no network")

    run_dir, results = sweep(tmp_path, "neatlogs", ensure=broken, run=None, out=lambda s: None)
    assert len(results) == len(plain_sdk())
    assert all(r["status"] == NOT_RUN and "no network" in r["reason"] for r in results)
    assert "NOT RUN" in (run_dir / "summary.txt").read_text()
    assert exit_code(results) == EXIT_ERROR


def test_summary_line_flags_expectation_drift():
    r = _fake_obs("a")
    r["observation"]["truth"]["expected_mismatch"] = ["tokens"]
    assert "tokens" in summary_line(r)
