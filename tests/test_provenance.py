import json
import subprocess

from trueup import provenance


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _add_fix(root, fid, message):
    fx = root / "fixes" / fid
    fx.mkdir(parents=True)
    (fx / "patch.diff").write_text("diff\n")
    (fx / "proof.json").write_text(json.dumps({
        "before": {"leads": {"a": [{}, {}], "b": [{}]}},
        "after": {"leads": {"a": [], "b": [{}]}},
        "new_mismatches": [],
    }))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", message)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()


def test_links_entire_record_only_when_trailer_present(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    with_sha = _add_fix(tmp_path, "with", "Add a fix\n\nEntire-Checkpoint: 01ABCDEFGHJKMNPQRSTVWXYZ00")
    _add_fix(tmp_path, "without", "Add another fix")
    monkeypatch.setattr(provenance, "explain", lambda root, cp: ["● Checkpoint " + cp])

    results = {p["finding"]: p for p in provenance.write_all(tmp_path)}

    w = results["with"]
    assert w["commit"]["checkpoint"] == "01ABCDEFGHJKMNPQRSTVWXYZ00"
    url = f"https://entire.io/gh/Jennycruzy/trueup/commit/{with_sha}"
    assert w["commit"]["entire_url"] == url
    assert w["proof"] == {"leads_before": 3, "leads_after": 1, "new_mismatches": 0}
    md = (tmp_path / "fixes" / "with" / "PROVENANCE.md").read_text()
    assert url in md and "What the session did" in md

    wo = results["without"]
    assert wo["commit"]["checkpoint"] is None and wo["commit"]["entire_url"] is None
    md = (tmp_path / "fixes" / "without" / "PROVENANCE.md").read_text()
    assert "No Entire record for this commit." in md
    assert "entire.io" not in md
    assert json.loads((tmp_path / "fixes" / "without" / "provenance.json").read_text())["commit"]["entire_url"] is None


def test_scrub_removes_private_paths_and_keys():
    text = ("failed in /root/trueup/src/x.py and /home/alice/venv/lib.py; "
            "key sk-abcdefghijklmnop123 api_key=supersecret token: abc123 tokens 13674k")
    out = provenance.scrub(text)
    for bad in ("/root", "/home", "alice", "sk-abcdefghijklmnop123", "supersecret", "abc123"):
        assert bad not in out
    assert "<private path>" in out
    assert "tokens 13674k" in out
