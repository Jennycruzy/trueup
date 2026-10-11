"""Durable workspace state for resumable Trueup workers.

The JSON evidence files remain portable and reviewable.  This database is the
local work ledger: workers checkpoint finished units here before moving on.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
CREATE TABLE IF NOT EXISTS leads (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    lead_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, lead_id)
);
CREATE TABLE IF NOT EXISTS findings (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, finding_id)
);
CREATE TABLE IF NOT EXISTS withdrawals (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    withdrawal_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, withdrawal_id)
);
CREATE TABLE IF NOT EXISTS fixes (
    finding_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS upstream_status (
    finding_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    """Small SQLite-backed run ledger. Connections are intentionally short lived."""

    def __init__(self, root: Path):
        path = root / ".trueup" / "state.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> State:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def begin_run(self, run_id: str, command: str, target: str) -> None:
        existing = self.connection.execute(
            "SELECT command, target FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if existing and existing != (command, target):
            raise ValueError(f"run {run_id} belongs to {existing[0]} {existing[1]}, not {command} {target}")
        self.connection.execute(
            "INSERT INTO runs(id, command, target, status, started_at) VALUES (?, ?, ?, 'running', ?) "
            "ON CONFLICT(id) DO UPDATE SET status = 'running', finished_at = NULL",
            (run_id, command, target, _now()),
        )
        self.connection.commit()

    def finish_run(self, run_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?", (status, _now(), run_id)
        )
        self.connection.commit()

    def save_observation(self, run_id: str, case_id: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO observations(run_id, case_id, status, payload, finished_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, case_id) DO UPDATE SET status=excluded.status, payload=excluded.payload, "
            "finished_at=excluded.finished_at",
            (run_id, case_id, str(payload["status"]), json.dumps(payload, default=str), _now()),
        )
        self.connection.commit()

    def observation(self, run_id: str, case_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT payload FROM observations WHERE run_id = ? AND case_id = ?", (run_id, case_id)
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()[:24]

    def save_check_results(self, run_id: str, leads: list[dict[str, Any]], findings: list[dict[str, Any]],
                           withdrawals: list[dict[str, Any]]) -> None:
        """Atomically replace a check run's derived records."""
        with self.connection:
            for table in ("leads", "findings", "withdrawals"):
                self.connection.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
            self.connection.executemany(
                "INSERT INTO leads(run_id, lead_id, payload) VALUES (?, ?, ?)",
                [(run_id, self._digest(x), json.dumps(x, default=str)) for x in leads],
            )
            self.connection.executemany(
                "INSERT INTO findings(run_id, finding_id, payload) VALUES (?, ?, ?)",
                [(run_id, str(x["id"]), json.dumps(x, default=str)) for x in findings],
            )
            self.connection.executemany(
                "INSERT INTO withdrawals(run_id, withdrawal_id, payload) VALUES (?, ?, ?)",
                [(run_id, self._digest(x), json.dumps(x, default=str)) for x in withdrawals],
            )

    def save_fix(self, finding_id: str, status: str, payload: dict[str, Any]) -> None:
        self._save_artifact("fixes", finding_id, status, payload)

    def save_upstream(self, finding_id: str, status: str, payload: dict[str, Any]) -> None:
        self._save_artifact("upstream_status", finding_id, status, payload)

    def _save_artifact(self, table: str, finding_id: str, status: str, payload: dict[str, Any]) -> None:
        if table not in {"fixes", "upstream_status"}:
            raise ValueError(f"unsupported artifact table: {table}")
        self.connection.execute(
            f"INSERT INTO {table}(finding_id, status, payload, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(finding_id) DO UPDATE SET status=excluded.status, payload=excluded.payload, "
            "updated_at=excluded.updated_at",
            (finding_id, status, json.dumps(payload, default=str), _now()),
        )
        self.connection.commit()

