from pathlib import Path

import pytest

from trueup.demo_export import CASES, demo_export


def test_demo_export_refuses_without_explicit_flag():
    with pytest.raises(ValueError, match="--yes-export-fake-traces"):
        demo_export(Path("."), "neatlogs", approved=False)


def test_demo_export_counts_and_uses_one_session():
    calls = []

    def run(_python, library, case, export_session=None):
        calls.append((library, case, export_session))
        return {"scenario": case, "status": "ran", "observation": {"trace": {"spans": [{}, {}]}}}

    result = demo_export(Path("."), "neatlogs", approved=True,
                         ensure=lambda _root, _lib: Path("python"), run=run, out=lambda _line: None)
    assert result["counted_spans"] == result["spans"] == 6
    assert [x[1] for x in calls] == list(CASES["neatlogs"]) * 2
    assert all(x[2] is None for x in calls[:3])
    assert len({x[2] for x in calls[3:]}) == 1
    assert calls[3][2].startswith("demo-neatlogs-")
