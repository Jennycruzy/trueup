from trueup.core import report
from trueup.core.model import Mismatch, Severity


def m(check, sev, kind="lead"):
    return Mismatch(field="f", truth="ERROR", trace={"x": 1}, severity=sev, check=check, kind=kind)


BY = [("a", [m("finish", Severity.MEDIUM), m("run_status", Severity.HIGH)]),
      ("b", [m("request_changed", Severity.LOW, "note")]),
      ("c", [])]


def test_table_columns_and_order():
    lines = report.table(BY).splitlines()
    assert lines[0].split() == ["scenario", "check", "expected", "actual", "severity"]
    assert lines[2].split()[:2] == ["a", "run_status"] and lines[2].endswith("HIGH")
    assert "request_changed (note)" in lines[4]


def test_empty_table():
    assert report.table([("a", [])]) == "no leads"


def test_long_cells_are_cut():
    long = [("a", [Mismatch("f", "x" * 200, None, Severity.LOW, "output")])]
    assert max(len(c) for c in report.rows(long)[0]) == report.CELL_MAX


def test_counts_exclude_notes():
    c = report.counts(BY)
    assert c["leads"] == 2 and c["notes"] == 1
    assert c["by_severity"] == {"high": 1, "medium": 1, "low": 0}
    assert c["by_check"] == {"finish": 1, "run_status": 1}
    assert c["scenarios_with_leads"] == 1


def test_payload_round_trips_mismatches():
    p = report.leads_payload("r1", "neatlogs", BY, [])
    assert p["scenarios"][0]["mismatches"][1]["check"] == "run_status"
    assert Mismatch.from_dict(p["scenarios"][0]["mismatches"][0]) == BY[0][1][0]
    assert "not a confirmed bug" in p["note"]
