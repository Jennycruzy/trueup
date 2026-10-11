"""Real subprocess runs in per-library venvs. Run with: uv run pytest -m e2e

Builds the venv on first use (needs network), one library at a time.
"""

from pathlib import Path
import os

import pytest

from trueup.runner import RAN, run_scenario, venvs

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[1]


E2E_LIBRARIES = [os.environ["TRUEUP_E2E_LIBRARY"]] if os.environ.get("TRUEUP_E2E_LIBRARY") else [
    "neatlogs", "openinference", "openllmetry"]


@pytest.fixture(scope="module", params=E2E_LIBRARIES)
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


def test_audit_runs_the_example_agent_with_overrides(lib):
    from trueup.runner.run import run_audit

    name, py = lib
    r = run_audit(py, name, ROOT / "examples" / "agent.py", "chat-500", {"/v1/chat/completions": "chat-500"})
    assert r["status"] == RAN, r["reason"]
    t = r["observation"]["truth"]
    assert t["outcome"] == "exception" and t["fake_log"][0]["scenario"] == "chat-500"


@pytest.mark.parametrize("scenario", ["lg-agent", "ag-run"])
def test_framework_scenario_runs_and_is_traced(lib, scenario):
    # A framework instrumentation that silently does nothing would give a run with no tool span.
    from trueup.core.adapters import ADAPTERS, tool_span_name

    name, py = lib
    r = run_scenario(py, name, scenario)
    assert r["status"] == RAN, r["reason"]
    obs = r["observation"]
    assert obs["truth"]["expected_mismatch"] == []
    tools = [tool_span_name(ADAPTERS[name], s) for s in obs["trace"]["spans"]]
    assert "get_weather" in tools
