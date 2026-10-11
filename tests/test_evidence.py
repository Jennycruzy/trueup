"""trueup verify and trueup report, on a copy of the committed evidence/ bundle. Offline."""

import json
import shutil
from pathlib import Path

import pytest

from trueup.cli import EXIT_MISMATCH, EXIT_OK, main
from trueup.evidence import VerifyFailed, sha256, verify, write_manifest

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


@pytest.fixture
def ev(tmp_path):
    d = tmp_path / "evidence"
    shutil.copytree(EVIDENCE, d)
    return d


def test_committed_bundle_verifies(ev):
    h = verify(ev, out=lambda _: None)
    assert h["findings"]["total"] == sum(b["findings"] for b in h["findings"]["by_library"].values())
    assert h["fixes_proven"] == len(h["fixes"])


def test_cli_verify_ok(ev, capsys):
    assert main(["verify", "--evidence", str(ev)]) == EXIT_OK
    assert "verify: OK" in capsys.readouterr().out


def test_cli_demo_shows_the_featured_proof(ev, capsys):
    assert main(["demo", "--evidence", str(ev)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Trueup demo (offline, verified evidence)" in out
    assert "Reality: ERROR (app raised InternalServerError)" in out
    assert "19 leads before -> 14 after" in out
    assert "result: PASS" in out


def test_cli_demo_reports_a_tampered_bundle_cleanly(ev, capsys):
    f = next((ev / "findings").iterdir()) / "spans.json"
    data = bytearray(f.read_bytes())
    data[0] ^= 1
    f.write_bytes(bytes(data))
    assert main(["demo", "--evidence", str(ev)]) == EXIT_MISMATCH
    err = capsys.readouterr().err
    assert "trueup demo:" in err and "Traceback" not in err


def test_one_changed_byte_fails(ev, capsys):
    f = next((ev / "findings").iterdir()) / "spans.json"
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 1
    f.write_bytes(bytes(data))
    with pytest.raises(VerifyFailed, match="sha256 differs"):
        verify(ev, out=lambda _: None)
    assert main(["verify", "--evidence", str(ev)]) == EXIT_MISMATCH
    assert "FAILED" in capsys.readouterr().err


def test_extra_and_missing_files_fail(ev):
    (ev / "extra.json").write_text("{}")
    with pytest.raises(VerifyFailed, match="not in the manifest"):
        verify(ev, out=lambda _: None)
    (ev / "extra.json").unlink()
    (ev / "runs.json").unlink()
    with pytest.raises(VerifyFailed, match="missing: runs.json"):
        verify(ev, out=lambda _: None)


def test_a_changed_number_with_a_matching_hash_still_fails(ev):
    """Rewriting headline.json and the manifest to match does not help: the numbers are recomputed."""
    h = json.loads((ev / "headline.json").read_text())
    h["findings"]["total"] += 1
    (ev / "headline.json").write_text(json.dumps(h))
    write_manifest(ev)
    with pytest.raises(VerifyFailed, match="headline.json findings"):
        verify(ev, out=lambda _: None)


def test_spans_that_no_longer_show_the_lead_fail(ev):
    """Editing a finding's saved spans so the bug is gone is caught by re-running the comparer."""
    d = ev / "findings" / "openllmetry-call_count-openai-agents-llm-spans-wrong"
    spans = json.loads((d / "spans.json").read_text())
    names = [s["name"] for s in spans]
    keep = [s for s in spans if s["name"] != "openai.response"]  # drop the duplicate LLM spans
    assert len(keep) < len(names)
    (d / "spans.json").write_text(json.dumps(keep))
    write_manifest(ev)
    with pytest.raises(VerifyFailed, match="does not find the lead"):
        verify(ev, out=lambda _: None)


def test_manifest_lists_every_file_with_its_sha256(ev):
    files = json.loads((ev / "manifest.json").read_text())["files"]
    on_disk = {str(p.relative_to(ev)) for p in ev.rglob("*") if p.is_file()} - {"manifest.json"}
    assert set(files) == on_disk
    assert all(sha256(ev / k) == v for k, v in files.items())


def test_bundle_contains_cfo_business_plan(ev):
    plan = ev / "business-plan.md"
    assert plan.is_file()
    assert "cfo.ai" in plan.read_text()


def test_report_is_static_and_complete(ev, tmp_path):
    out = tmp_path / "index.html"
    assert main(["report", "--evidence", str(ev), "--out", str(out)]) == EXIT_OK
    html = out.read_text()
    assert "<script" not in html.lower() and "stylesheet" not in html.lower()
    assert "prefers-color-scheme:dark" in html and 'name="viewport"' in html
    order = [html.index(x) for x in ("<h2>Headline", "One finding, start to finish", "<h2>All findings",
                                      "<h2>Withdrawn leads", "<h2>Upstream drafts")]
    assert order == sorted(order)
    assert "not yet posted" in html.lower()
    first = out.read_bytes()
    main(["report", "--evidence", str(ev), "--out", str(out)])
    assert out.read_bytes() == first  # same bundle, same page


def test_report_refuses_a_changed_bundle(ev, tmp_path):
    (ev / "runs.json").write_text("[]\n")
    assert main(["report", "--evidence", str(ev), "--out", str(tmp_path / "x.html")]) == EXIT_MISMATCH
    assert not (tmp_path / "x.html").exists()


def test_committed_page_matches_the_bundle(tmp_path):
    out = tmp_path / "index.html"
    main(["report", "--evidence", str(EVIDENCE), "--out", str(out)])
    assert out.read_text() == (EVIDENCE.parent / "docs" / "index.html").read_text()


def test_no_machine_paths_in_bundle():
    for p in EVIDENCE.rglob("*"):
        if p.is_file():
            t = p.read_text(errors="replace")
            assert "/root/" not in t and "/home/" not in t, p
