"""The deterministic, offline judge demo built from the verified evidence bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from trueup.evidence import _load, verify

DEFAULT_FINDING = "openinference-run_status-openai-agents-top-level-span-status-ok"


class DemoError(RuntimeError):
    """The evidence bundle cannot support the requested demo."""


def _lead_count(proof: dict[str, Any], phase: str) -> int:
    return sum(len(leads) for leads in proof[phase]["leads"].values())


def demo(
    evidence: Path,
    finding_id: str = DEFAULT_FINDING,
    out: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Print one complete before/after proof without keys, network, or model calls.

    The demo deliberately reads the committed evidence bundle and verifies it first. It is a
    presentation path, not a substitute for ``sweep``, ``check`` or ``fix``.
    """
    verify(evidence, out=lambda _: None)
    finding_dir = evidence / "findings" / finding_id
    finding_path = finding_dir / "finding.json"
    proof_path = finding_dir / "proof.json"
    if not finding_path.exists():
        raise DemoError(f"finding not in evidence bundle: {finding_id}")
    if not proof_path.exists():
        raise DemoError(f"finding has no proof: {finding_id}")

    finding = _load(finding_path)
    proof = _load(proof_path)
    new_mismatches = proof.get("new_mismatches", [])
    if not finding.get("fixed") or new_mismatches:
        raise DemoError(f"finding is not proven fixed: {finding_id}")

    example = finding["example"]
    before = _lead_count(proof, "before")
    after = _lead_count(proof, "after")
    scenarios = len(proof["rows"])
    out("Trueup demo (offline, verified evidence)")
    out(f"finding: {finding['title']} [{finding['severity']}]")
    out(f"1. Reality: {example['truth']}")
    out(f"2. Recorded trace: {example['trace']}")
    out(f"3. Confirmed: the mismatch reproduced across {scenarios} scenarios")
    out(f"4. Repaired: verified patch {proof['commit'][:12]}")
    out(f"5. Proven: {before} leads before -> {after} after; {len(new_mismatches)} new mismatches")
    out("result: PASS")
    return {"finding": finding_id, "before_leads": before, "after_leads": after,
            "scenarios": scenarios, "commit": proof["commit"], "new_mismatches": new_mismatches}
