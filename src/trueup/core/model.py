"""Data model. Plain dataclasses with to_dict/from_dict. No I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        # Higher rank means more severe.
        return {"high": 3, "medium": 2, "low": 1}[self.value]

    def __lt__(self, other: Severity) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: Severity) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: Severity) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: Severity) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank >= other.rank


@dataclass(frozen=True)
class Observation:
    """What really happened (truth) next to what the trace recorded (trace)."""

    truth: dict[str, Any]
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"truth": dict(self.truth), "trace": dict(self.trace)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Observation:
        return cls(truth=dict(d["truth"]), trace=dict(d["trace"]))


@dataclass(frozen=True)
class Mismatch:
    """One field where truth and trace disagree."""

    field: str
    truth: Any
    trace: Any
    severity: Severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "truth": self.truth,
            "trace": self.trace,
            "severity": self.severity.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Mismatch:
        return cls(
            field=d["field"],
            truth=d["truth"],
            trace=d["trace"],
            severity=Severity(d["severity"]),
        )


@dataclass(frozen=True)
class Run:
    """One scenario run against the fake provider."""

    id: str
    scenario: str
    library: str
    observation: Observation
    mismatches: tuple[Mismatch, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scenario": self.scenario,
            "library": self.library,
            "observation": self.observation.to_dict(),
            "mismatches": [m.to_dict() for m in self.mismatches],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Run:
        return cls(
            id=d["id"],
            scenario=d["scenario"],
            library=d["library"],
            observation=Observation.from_dict(d["observation"]),
            mismatches=tuple(Mismatch.from_dict(m) for m in d.get("mismatches", [])),
        )


@dataclass(frozen=True)
class Finding:
    """A confirmed, deduplicated problem in a tracing library."""

    id: str
    title: str
    library: str
    severity: Severity
    run_ids: tuple[str, ...] = ()
    cause: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "library": self.library,
            "severity": self.severity.value,
            "run_ids": list(self.run_ids),
            "cause": self.cause,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Finding:
        return cls(
            id=d["id"],
            title=d["title"],
            library=d["library"],
            severity=Severity(d["severity"]),
            run_ids=tuple(d.get("run_ids", [])),
            cause=d.get("cause"),
            details=dict(d.get("details", {})),
        )
