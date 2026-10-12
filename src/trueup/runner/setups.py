"""Each target library's recommended setup, wired to an in-memory exporter.

Runs inside the child process, in the library's own venv. Each setup takes the
scenario's framework ("none", "langchain", "langgraph", "openai-agents") and
returns the InMemorySpanExporter and a flush function.

A framework instrumentation does nothing, without an error, when the framework
package is missing: neatlogs skips an instrumentation it finds "not installed",
and OpenLLMetry only instruments what it can import. So before a framework
scenario runs, check_framework() imports the framework and confirms an
instrumentor for it is active, and raises if not. The runner reports that as
NOT RUN instead of a quiet, empty trace.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Callable

# Environment for every child. Content capture on, all outbound telemetry off.
CHILD_ENV = {
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
    "TRACELOOP_TRACE_CONTENT": "true",
    "TRACELOOP_TELEMETRY": "false",
    # A neatlogs exporter pointed at a dead endpoint retries for ~200 s per run.
    "NEATLOGS_DISABLE_EXPORT": "true",
    "OTEL_SDK_DISABLED": "false",
    "OTEL_TRACES_EXPORTER": "none",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_LOGS_EXPORTER": "none",
    "OPENAI_API_KEY": "trueup-fake",
    "ANTHROPIC_API_KEY": "trueup-fake",
}
# Env vars removed from the child so no real key or endpoint is ever used.
CHILD_ENV_DROP = (
    "NEATLOGS_API_KEY",
    "NEATLOGS_ENDPOINT",
    "TRACELOOP_API_KEY",
    "TRACELOOP_BASE_URL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
)

# The framework packages every venv gets, so framework instrumentations have something to patch.
# "langchain" itself: neatlogs checks `import langchain` and skips its LangChain instrumentation without it.
FRAMEWORK_PACKAGES = ["langchain", "langchain-openai", "langgraph", "openai-agents"]
# Modules a framework scenario imports. Missing one means the instrumentation would be a no-op.
FRAMEWORK_MODULES: dict[str, tuple[str, ...]] = {
    "langchain": ("langchain_core", "langchain_openai"),
    "langgraph": ("langchain_core", "langchain_openai", "langgraph"),
    "openai-agents": ("agents",),
}
# A part of the instrumentor's module path that names the framework.
FRAMEWORK_INSTRUMENTOR: dict[str, str] = {
    "langchain": "langchain",
    "langgraph": "langchain",  # LangGraph runs are traced through LangChain callbacks
    "openai-agents": "openai_agents",
}

# Packages per library venv.
PACKAGES: dict[str, list[str]] = {
    # neatlogs depends on the OpenInference LangChain and OpenAI Agents instrumentors. Its
    # README installs the frameworks through extras; the langchain extra also pulls vector
    # stores (chromadb, qdrant), so we install the framework packages directly.
    "neatlogs": ["neatlogs", "openai", "anthropic", "opentelemetry-sdk", *FRAMEWORK_PACKAGES],
    "openinference": [
        "neatlogs",
        "openinference-instrumentation-openai",
        "openinference-instrumentation-anthropic",
        "openinference-instrumentation-langchain",
        "openinference-instrumentation-openai-agents",
        "openai",
        "anthropic",
        "opentelemetry-sdk",
        *FRAMEWORK_PACKAGES,
    ],
    # traceloop-sdk imports httpx without declaring it; openai no longer pulls it in.
    # It already depends on its LangChain and OpenAI Agents instrumentations.
    "openllmetry": ["neatlogs", "traceloop-sdk", "httpx", "openai", "anthropic", *FRAMEWORK_PACKAGES],
}
# Distributions whose versions are recorded with each observation.
VERSIONED: dict[str, list[str]] = {
    "neatlogs": ["neatlogs", "openinference-instrumentation-langchain", "openinference-instrumentation-openai-agents",
                 "openai", "anthropic", "opentelemetry-sdk", "langchain-core", "langchain-openai", "langgraph",
                 "openai-agents"],
    "openinference": [
        "openinference-instrumentation-openai",
        "openinference-instrumentation-anthropic",
        "openinference-instrumentation-langchain",
        "openinference-instrumentation-openai-agents",
        "openai",
        "anthropic",
        "opentelemetry-sdk",
        "langchain-core",
        "langchain-openai",
        "langgraph",
        "openai-agents",
    ],
    "openllmetry": [
        "traceloop-sdk",
        "opentelemetry-instrumentation-openai",
        "opentelemetry-instrumentation-anthropic",
        "opentelemetry-instrumentation-langchain",
        "opentelemetry-instrumentation-openai-agents",
        "openai",
        "anthropic",
        "opentelemetry-sdk",
        "langchain-core",
        "langchain-openai",
        "langgraph",
        "openai-agents",
    ],
}
LIBRARIES = tuple(PACKAGES)


class FrameworkNotTraced(RuntimeError):
    """The framework or its instrumentation is missing, so the run would trace nothing."""


def _all_subclasses(cls: type) -> list[type]:
    out = []
    for sub in cls.__subclasses__():
        out += [sub, *_all_subclasses(sub)]
    return out


def active_instrumentors() -> list[str]:
    """Module paths of OTel instrumentors that are instrumented right now (they are singletons)."""
    try:
        from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
    except ImportError:
        return []
    return sorted({
        f"{c.__module__}.{c.__name__}"
        for c in _all_subclasses(BaseInstrumentor)
        if getattr(c.__dict__.get("_instance"), "_is_instrumented_by_opentelemetry", False)
    })


def check_framework(framework: str, active: Callable[[], list[str]] = active_instrumentors) -> None:
    """Raise FrameworkNotTraced unless the framework imports and an instrumentor for it is active."""
    if framework == "none":
        return
    for module in FRAMEWORK_MODULES[framework]:
        try:
            importlib.import_module(module)
        except ImportError as e:
            raise FrameworkNotTraced(f"{framework}: cannot import {module} ({e}); its instrumentation would do nothing") from None
    token = FRAMEWORK_INSTRUMENTOR[framework]
    names = active()
    if not any(token in n for n in names):
        raise FrameworkNotTraced(f"{framework}: no active instrumentor with {token!r} in its module; "
                                 f"active: {', '.join(names) or 'none'}")


def neatlogs_instrumentations(framework: str) -> list[str]:
    """Keys from the neatlogs README: the framework's own key, or the provider SDKs for plain use."""
    return {
        "none": ["openai", "anthropic"],
        "langchain": ["langchain"],
        "langgraph": ["langchain", "langgraph"],
        "openai-agents": ["openai_agents"],
    }[framework]


def quiet_agents_sdk() -> None:
    """Drop the Agents SDK's own trace uploader (it posts to api.openai.com). Instrumentor processors stay."""
    try:
        from agents.tracing import get_trace_provider
        from agents.tracing.processors import default_processor
    except ImportError:
        return
    multi = getattr(get_trace_provider(), "_multi_processor", None)
    if multi is not None:
        multi.set_processors([p for p in multi._processors if p is not default_processor()])


def neatlogs_init_kwargs(tracer_provider: Any, framework: str = "none") -> dict[str, Any]:
    """neatlogs.init arguments. Export is off and no endpoint is given."""
    exporting = os.environ.get("TRUEUP_DEMO_EXPORT") == "1"
    return {
        "api_key": os.environ.get("NEATLOGS_API_KEY", "trueup-fake"),
        "instrumentations": neatlogs_instrumentations(framework),
        "disable_export": not exporting,
        "tracer_provider": tracer_provider,
        "register_shutdown_handlers": False,
        "workflow_name": "trueup-demo" if exporting else None,
        "user_id": "jenny-builds" if exporting else None,
        "tags": ["demo"] if exporting else None,
    }


def setup_neatlogs(framework: str = "none"):
    import neatlogs
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    neatlogs.init(**neatlogs_init_kwargs(provider, framework))
    # Added after init so we see spans after neatlogs' own processor ran.
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def flush() -> None:
        neatlogs.flush(timeout_millis=5000)
        provider.force_flush(5000)

    return exporter, flush


def setup_openinference(framework: str = "none"):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # The framework's instrumentor alone, as its docs show; the SDK ones for plain SDK use.
    if framework in ("langchain", "langgraph"):
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().instrument(tracer_provider=provider)
    elif framework == "openai-agents":
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

        OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)
    else:
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=provider)
        AnthropicInstrumentor().instrument(tracer_provider=provider)
    if os.environ.get("TRUEUP_DEMO_EXPORT") == "1":
        import neatlogs

        kwargs = neatlogs_init_kwargs(provider, framework)
        kwargs["instrumentations"] = []
        neatlogs.init(**kwargs)

    def flush() -> None:
        if os.environ.get("TRUEUP_DEMO_EXPORT") == "1":
            import neatlogs
            neatlogs.flush(timeout_millis=5000)
        provider.force_flush(5000)

    return exporter, flush


def setup_openllmetry(framework: str = "none"):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from traceloop.sdk import Traceloop

    exporter = InMemorySpanExporter()
    active_exporter: Any = exporter
    resource_attributes = {}
    session_processor = None
    if os.environ.get("TRUEUP_DEMO_EXPORT") == "1":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

        class FanoutExporter(SpanExporter):
            def __init__(self, *targets: Any) -> None:
                self.targets = targets

            def export(self, spans: Any) -> SpanExportResult:
                results = [target.export(spans) for target in self.targets]
                return SpanExportResult.SUCCESS if all(x == SpanExportResult.SUCCESS for x in results) \
                    else SpanExportResult.FAILURE

            def shutdown(self) -> None:
                for target in self.targets:
                    target.shutdown()

            def force_flush(self, timeout_millis: int = 30000) -> bool:
                return all(getattr(target, "force_flush", lambda _timeout: True)(timeout_millis)
                           for target in self.targets)

        from opentelemetry.sdk.trace import SpanProcessor

        class DemoSessionProcessor(SpanProcessor):
            def on_start(self, span: Any, parent_context: Any = None) -> None:
                # Some OpenLLMetry roots have a remote/non-recording parent, so make the
                # explicit demo identity available on every exported span.
                span.set_attribute("neatlogs.session.id", os.environ["TRUEUP_DEMO_SESSION"])

            def on_end(self, span: Any) -> None:
                pass

        endpoint = os.environ.get("NEATLOGS_ENDPOINT", "https://ingest.neatlogs.com").rstrip("/") + "/v1/traces"
        remote = OTLPSpanExporter(endpoint=endpoint, headers={"x-api-key": os.environ["NEATLOGS_API_KEY"]})
        active_exporter = FanoutExporter(exporter, remote)
        session_processor = DemoSessionProcessor()
        resource_attributes = {
            "service.name": "trueup-demo",
            "neatlogs.workflow_name": "trueup-demo",
            "neatlogs.tags": "demo",
            "user.id": "jenny-builds",
        }
    # Same call for every framework: Traceloop.init instruments whatever it can import.
    init_kwargs: dict[str, Any] = {"app_name": "trueup", "disable_batch": True, "telemetry_enabled": False,
                                   "resource_attributes": resource_attributes}
    if session_processor is None:
        init_kwargs["exporter"] = active_exporter
    else:
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        init_kwargs["processor"] = [session_processor, SimpleSpanProcessor(active_exporter)]
    Traceloop.init(**init_kwargs)

    def flush() -> None:
        from opentelemetry import trace

        p = trace.get_tracer_provider()
        if hasattr(p, "force_flush"):
            p.force_flush(5000)

    return exporter, flush


SETUPS: dict[str, Callable[[str], tuple[Any, Callable[[], None]]]] = {
    "neatlogs": setup_neatlogs,
    "openinference": setup_openinference,
    "openllmetry": setup_openllmetry,
}
