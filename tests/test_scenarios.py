import pytest

from trueup.fake import AGENT_SCENARIOS
from trueup.fake import SCENARIOS as FAKE_SCENARIOS
from trueup.fake import FakeProvider
from trueup.runner import apps, framework_apps, truth
from trueup.scenarios import ALL, BUILT, get, plain_sdk, select
from trueup.scenarios import library as lib


def test_ids_unique():
    assert len({s.id for s in ALL}) == len(ALL)


def test_plain_sdk_cases_are_built_and_cover_three_apis():
    plain = plain_sdk()
    assert all(s.status == BUILT for s in plain)
    assert {(s.provider, s.api) for s in plain} == {
        ("openai", "chat"),
        ("openai", "responses"),
        ("anthropic", "messages"),
    }


def test_framework_cases_are_built():
    fw = [s for s in ALL if not s.plain_sdk]
    assert len(fw) == 20 and all(s.status == BUILT for s in fw)
    assert {s.framework for s in fw} == {"langchain", "langgraph", "openai-agents"}


def test_built_scenarios_point_at_real_apps_and_fake_models():
    for s in ALL:
        assert s.app in apps.APPS, s.id
        assert s.model in FAKE_SCENARIOS + AGENT_SCENARIOS, s.id


def test_every_fake_scenario_is_used():
    assert set(FAKE_SCENARIOS + AGENT_SCENARIOS) <= {s.model for s in ALL}


def test_select_by_framework():
    assert len(select("all")) == len(ALL)
    assert select("none") == plain_sdk()
    assert {s.framework for s in select("langchain")} == {"langchain", "langgraph"}
    assert len(select("langchain")) == 12 and len(select("openai-agents")) == 8


def test_get_unknown():
    with pytest.raises(KeyError):
        get("nope")


@pytest.mark.parametrize("scenario", ALL, ids=lambda s: s.id)
def test_expected_truth_matches_untraced_run(scenario):
    # Runs the app in-process with no tracing library, so the expectations
    # in the library are checked against what really happens, with the real
    # openai, anthropic, LangChain, LangGraph and Agents SDKs.
    framework_apps.TOOL_RUNS.clear()
    with FakeProvider() as f:
        try:
            app = {"outcome": "ok", "result": apps.APPS[scenario.app](f.base_url, scenario.model)}
        except Exception as e:
            app = {"outcome": "exception", "exception_type": type(e).__name__}
        t = truth.derive(f.log.entries(), app, framework_apps.TOOL_RUNS)
    assert truth.check_expected(scenario.expected, t) == []


def test_to_dict_has_expected_fields():
    d = get("oa-chat-plain").to_dict()
    assert set(d) == {"id", "provider", "api", "framework", "does", "app", "model", "expected", "status"}
