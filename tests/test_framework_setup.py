"""Framework setups. A framework instrumentation that silently does nothing must fail loudly.

Found while building: neatlogs.init(instrumentations=["langchain"]) checks
`import langchain`; with only langchain-core and langchain-openai installed it
logs "Skipped: langchain (not installed)" and traces nothing, without an error.
"""

import importlib

import pytest

from trueup.runner import setups
from trueup.runner.setups import FrameworkNotTraced, check_framework

OI_LANGCHAIN = "openinference.instrumentation.langchain.LangChainInstrumentor"
OI_AGENTS = "openinference.instrumentation.openai_agents.OpenAIAgentsInstrumentor"


def test_missing_framework_package_fails_loudly(monkeypatch):
    real = importlib.import_module

    def no_agents(name, *a, **kw):
        if name == "agents":
            raise ImportError("No module named 'agents'")
        return real(name, *a, **kw)

    monkeypatch.setattr(setups.importlib, "import_module", no_agents)
    with pytest.raises(FrameworkNotTraced, match="cannot import agents"):
        check_framework("openai-agents", active=lambda: [OI_AGENTS])


def test_inactive_framework_instrumentation_fails_loudly():
    # The neatlogs case: the framework imports, but no instrumentor for it was turned on.
    with pytest.raises(FrameworkNotTraced, match="no active instrumentor"):
        check_framework("langchain", active=lambda: ["opentelemetry.instrumentation.threading.ThreadingInstrumentor"])
    with pytest.raises(FrameworkNotTraced):
        check_framework("openai-agents", active=lambda: [OI_LANGCHAIN])


def test_active_framework_instrumentation_passes():
    check_framework("langchain", active=lambda: [OI_LANGCHAIN])
    check_framework("langgraph", active=lambda: [OI_LANGCHAIN])
    check_framework("openai-agents", active=lambda: [OI_AGENTS])
    check_framework("openai-agents", active=lambda: [
        "opentelemetry.instrumentation.openai_agents.OpenAIAgentsInstrumentor"])
    check_framework("none", active=lambda: [])


def test_every_venv_installs_the_frameworks_and_langchain_itself():
    for lib, packages in setups.PACKAGES.items():
        for p in ("langchain", "langchain-openai", "langgraph", "openai-agents"):
            assert p in packages, (lib, p)
    assert "openinference-instrumentation-langchain" in setups.PACKAGES["openinference"]
    assert "openinference-instrumentation-openai-agents" in setups.PACKAGES["openinference"]


def test_neatlogs_uses_readme_framework_keys():
    assert setups.neatlogs_instrumentations("langchain") == ["langchain"]
    assert setups.neatlogs_instrumentations("langgraph") == ["langchain", "langgraph"]
    assert setups.neatlogs_instrumentations("openai-agents") == ["openai_agents"]
    kw = setups.neatlogs_init_kwargs(object(), "openai-agents")
    assert kw["instrumentations"] == ["openai_agents"] and kw["disable_export"] is True


def test_quiet_agents_sdk_drops_only_the_openai_uploader():
    from agents.tracing import add_trace_processor, get_trace_provider
    from agents.tracing.processors import default_processor

    class Mine:
        def __getattr__(self, name):
            return lambda *a, **kw: None

    multi = get_trace_provider()._multi_processor
    before = list(multi._processors)
    mine = Mine()
    try:
        add_trace_processor(mine)
        setups.quiet_agents_sdk()
        assert mine in multi._processors and default_processor() not in multi._processors
    finally:
        multi.set_processors(before)
