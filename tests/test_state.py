import sqlite3
from pathlib import Path

import pytest

from trueup.state import State
from trueup.sweep import sweep


def result(case: str) -> dict:
    return {"scenario": case, "library": "neatlogs", "status": "not_run", "reason": "test", "seconds": 0}


def test_state_has_all_spec_entities(tmp_path):
    with State(tmp_path):
        pass
    db = sqlite3.connect(tmp_path / ".trueup" / "state.db")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "observations", "leads", "findings", "withdrawals", "fixes", "upstream_status"} <= tables


def test_run_id_cannot_be_reused_for_another_target(tmp_path):
    with State(tmp_path) as state:
        state.begin_run("r1", "sweep", "neatlogs")
        with pytest.raises(ValueError, match="belongs to"):
            state.begin_run("r1", "sweep", "openinference")


def test_sweep_resumes_finished_cases(tmp_path, monkeypatch):
    class Scenario:
        id = "one"

    monkeypatch.setattr("trueup.sweep.select", lambda _: [Scenario()])
    calls = []

    def run(_python: Path, _library: str, case: str):
        calls.append(case)
        return result(case)

    kwargs = {"run_id": "resume-me", "ensure": lambda *_: Path("/python"), "run": run, "out": lambda _: None}
    sweep(tmp_path, "neatlogs", **kwargs)
    sweep(tmp_path, "neatlogs", **kwargs)
    assert calls == ["one"]


def test_check_fix_and_upstream_records_are_durable(tmp_path):
    with State(tmp_path) as state:
        state.begin_run("check-1", "check", "neatlogs")
        state.save_check_results("check-1", [{"lead": 1}], [{"id": "finding-1"}], [{"why": "withdrawn"}])
        state.save_fix("finding-1", "fixed", {"tries": 2})
        state.save_upstream("finding-1", "drafted", {"posted": False})
    db = sqlite3.connect(tmp_path / ".trueup" / "state.db")
    assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
    assert db.execute("SELECT finding_id FROM findings").fetchone()[0] == "finding-1"
    assert db.execute("SELECT count(*) FROM withdrawals").fetchone()[0] == 1
    assert db.execute("SELECT status FROM fixes").fetchone()[0] == "fixed"
    assert db.execute("SELECT status FROM upstream_status").fetchone()[0] == "drafted"

