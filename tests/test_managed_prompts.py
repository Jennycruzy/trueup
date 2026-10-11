from types import SimpleNamespace
import hashlib
import json
from pathlib import Path

from trueup.managed_prompts import production
from trueup.planner import SYSTEM as PLANNER
from trueup.fixer.patch import JSON_ONLY, SYSTEM as FIXER


def test_managed_prompt_uses_production_label():
    calls = []

    def fetch(name, **kwargs):
        calls.append((name, kwargs))
        return SimpleNamespace(content="managed")

    assert production("trueup-planner", "local", fetch=fetch) == "managed"
    assert calls == [("trueup-planner", {"label": "production"})]


def test_managed_prompt_has_offline_and_failure_fallbacks():
    assert production("trueup-planner", "local", enabled=False) == "local"
    assert production("trueup-planner", "local", fetch=lambda *_a, **_k: (_ for _ in ()).throw(OSError())) == "local"


def test_committed_prompt_copies_are_exact_and_hashed():
    root = Path(__file__).resolve().parents[1] / "prompts"
    expected = {"planner-v1.txt": PLANNER, "planner-v2.txt": PLANNER,
                "fixer-v1.txt": FIXER, "fixer-v2.txt": FIXER + JSON_ONLY}
    manifest = json.loads((root / "manifest.json").read_text())
    for name, text in expected.items():
        data = (root / name).read_bytes()
        assert data.decode().rstrip("\n") == text
        assert hashlib.sha256(data).hexdigest() == manifest[name]
