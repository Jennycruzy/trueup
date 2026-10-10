"""Real subprocess runs in per-library venvs. Run with: uv run pytest -m e2e

Builds the venv on first use (needs network), one library at a time.
"""

from pathlib import Path

import pytest

from trueup.runner import RAN, run_scenario, venvs

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", params=["neatlogs", "openinference", "openllmetry"])
def lib(request):
    return request.param, venvs.ensure(ROOT, request.param)


def test_plain_chat_produces_truth_and_spans(lib):
    name, py = lib
    r = run_scenario(py, name, "oa-chat-plain")
    assert r["status"] == RAN, r["reason"]
    obs = r["observation"]
    assert obs["truth"]["calls"] == 1 and obs["truth"]["outcome"] == "ok"
    assert obs["truth"]["expected_mismatch"] == []
    assert obs["trace"]["spans"], "no spans exported"
    assert obs["trace"]["versions"][next(iter(obs["trace"]["versions"]))]


def test_app_exception_is_recorded(lib):
    name, py = lib
    r = run_scenario(py, name, "an-529")
    assert r["status"] == RAN, r["reason"]
    app = r["observation"]["truth"]["app"]
    assert app["outcome"] == "exception" and app["exception_type"] == "OverloadedError"


def test_neatlogs_run_is_fast_with_export_disabled():
    # Trap 4: export to a dead endpoint made this take ~200 s.
    py = venvs.ensure(ROOT, "neatlogs")
    r = run_scenario(py, "neatlogs", "oa-chat-stream-cut", timeout=60)
    assert r["status"] == RAN, r["reason"]
    assert r["seconds"] < 30
