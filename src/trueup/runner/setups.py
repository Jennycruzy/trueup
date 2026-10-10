"""Each target library's recommended setup, wired to an in-memory exporter.

Runs inside the child process, in the library's own venv. Each setup returns
the InMemorySpanExporter and a flush function.
"""

from __future__ import annotations

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

# Packages per library venv.
PACKAGES: dict[str, list[str]] = {
    "neatlogs": ["neatlogs", "openai", "anthropic", "opentelemetry-sdk"],
    "openinference": [
        "openinference-instrumentation-openai",
        "openinference-instrumentation-anthropic",
        "openai",
        "anthropic",
        "opentelemetry-sdk",
    ],
    # traceloop-sdk imports httpx without declaring it; openai no longer pulls it in.
    "openllmetry": ["traceloop-sdk", "httpx", "openai", "anthropic"],
}
# Distributions whose versions are recorded with each observation.
VERSIONED: dict[str, list[str]] = {
    "neatlogs": ["neatlogs", "openai", "anthropic", "opentelemetry-sdk"],
    "openinference": [
        "openinference-instrumentation-openai",
        "openinference-instrumentation-anthropic",
        "openai",
        "anthropic",
        "opentelemetry-sdk",
    ],
    "openllmetry": [
        "traceloop-sdk",
        "opentelemetry-instrumentation-openai",
        "opentelemetry-instrumentation-anthropic",
        "openai",
        "anthropic",
        "opentelemetry-sdk",
    ],
}
LIBRARIES = tuple(PACKAGES)


def neatlogs_init_kwargs(tracer_provider: Any) -> dict[str, Any]:
    """neatlogs.init arguments. Export is off and no endpoint is given."""
    return {
        "api_key": "trueup-fake",
        "instrumentations": ["openai", "anthropic"],
        "disable_export": True,
        "tracer_provider": tracer_provider,
        "register_shutdown_handlers": False,
    }


def setup_neatlogs():
    import neatlogs
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    neatlogs.init(**neatlogs_init_kwargs(provider))
    # Added after init so we see spans after neatlogs' own processor ran.
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def flush() -> None:
        neatlogs.flush(timeout_millis=5000)
        provider.force_flush(5000)

    return exporter, flush


def setup_openinference():
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    AnthropicInstrumentor().instrument(tracer_provider=provider)
    return exporter, lambda: provider.force_flush(5000)


def setup_openllmetry():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from traceloop.sdk import Traceloop

    exporter = InMemorySpanExporter()
    Traceloop.init(app_name="trueup", exporter=exporter, disable_batch=True, telemetry_enabled=False)

    def flush() -> None:
        from opentelemetry import trace

        p = trace.get_tracer_provider()
        if hasattr(p, "force_flush"):
            p.force_flush(5000)

    return exporter, flush


SETUPS: dict[str, Callable[[], tuple[Any, Callable[[], None]]]] = {
    "neatlogs": setup_neatlogs,
    "openinference": setup_openinference,
    "openllmetry": setup_openllmetry,
}
