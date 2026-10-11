"""Where a finding's code lives in each library, and how that package runs its own tests.

A target is keyed by (library, code path) as the checker groups findings. It names
the packages in the library's repo the fix may touch, the symbols to start the
search from (the wrapper), the symbols that show how the library already gets a
similar case right, and the test requirements of each package.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REPOS = {
    "neatlogs": "https://github.com/neatlogs/neatlogs",
    "openinference": "https://github.com/Arize-ai/openinference",
    "openllmetry": "https://github.com/traceloop/openllmetry",
}
ISSUE_REPOS = {"neatlogs": "neatlogs/neatlogs", "openinference": "Arize-ai/openinference",
               "openllmetry": "traceloop/openllmetry"}


@dataclass(frozen=True)
class Package:
    path: str  # in the repo
    dist: str  # distribution name, as installed in the scenario venv
    tests: str = "tests"  # relative to path
    # Test requirements: "group:<name>" reads [dependency-groups] of the package's pyproject,
    # "file:<name>" a requirements file in the package; anything else is a requirement.
    test_deps: tuple[str, ...] = ()
    # Local packages of the same repo the tests need from source (editable).
    local_deps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Target:
    library: str
    code_path: str
    packages: tuple[Package, ...]
    seeds: tuple[str, ...]  # wrapper functions or classes to locate
    reference_seeds: tuple[str, ...] = ()  # where the library gets a similar case right
    reference_note: str = ""  # the rule the fix must follow (OTel GenAI conventions)
    extra: dict[str, str] = field(default_factory=dict)


_OLL_SEMCONV = "packages/opentelemetry-semantic-conventions-ai"
_OLL_TEST = ("group:test", "group:dev")
_OI_CORE = ("python/openinference-semantic-conventions", "python/openinference-instrumentation")

TARGETS: dict[tuple[str, str], Target] = {
    ("openllmetry", "openai-agents"): Target(
        library="openllmetry", code_path="openai-agents",
        packages=(
            Package("packages/opentelemetry-instrumentation-openai-agents", "opentelemetry-instrumentation-openai-agents",
                    test_deps=_OLL_TEST, local_deps=(_OLL_SEMCONV, "packages/opentelemetry-instrumentation-openai")),
            Package("packages/opentelemetry-instrumentation-openai", "opentelemetry-instrumentation-openai",
                    test_deps=_OLL_TEST, local_deps=(_OLL_SEMCONV,)),
        ),
        seeds=("OpenTelemetryTracingProcessor", "on_span_start", "on_span_end", "responses_get_or_create_wrapper",
               "async_responses_get_or_create_wrapper"),
        reference_seeds=("SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY",),
        reference_note=("OTel GenAI conventions: one inference span per model call. OpenInference records the "
                        "same Agents SDK runs with one LLM span per call. Inside OpenLLMetry, the LangChain "
                        "instrumentation sets SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY in the context so the "
                        "provider instrumentation under it does not record the same call again."),
    ),
    ("openinference", "openai-agents"): Target(
        library="openinference", code_path="openai-agents",
        packages=(
            Package("python/instrumentation/openinference-instrumentation-openai-agents",
                    "openinference-instrumentation-openai-agents", test_deps=("file:test-requirements.txt", "pytest"),
                    local_deps=_OI_CORE),
        ),
        seeds=("OpenInferenceTracingProcessor", "on_trace_start", "on_trace_end", "on_span_end", "_get_span_status"),
        reference_note=("OTel conventions: a span whose operation failed has status ERROR. The root span covers the "
                        "whole run, so it must not be OK when the run raised. Which SDK span carries the error "
                        "differs by failure (the agent span, a turn span or a response span; see the spans "
                        "below). A run whose tool raised but which still finished must stay OK: the SDK marks "
                        "that function span with a non-fatal error."),
    ),
    ("neatlogs", "anthropic messages stream"): Target(
        library="neatlogs", code_path="anthropic messages stream",
        packages=(Package(".", "neatlogs", tests="tests/unit", test_deps=("group:dev", "anthropic", "openai")),),
        seeds=("patched_stream", "_SyncStreamManagerWrapper", "_SyncStreamIterator", "_AsyncStreamManagerWrapper",
               "_AsyncStreamIterator", "_finalize_stream"),
        reference_seeds=("_err",),
        reference_note=("OTel conventions: a span whose operation failed has status ERROR with an exception "
                        "event. neatlogs already does this for messages.create(stream=True), through _err."),
    ),
}


def get(library: str, code_path: str) -> Target:
    try:
        return TARGETS[(library, code_path)]
    except KeyError:
        raise KeyError(f"no fix target for {library} / {code_path!r}; known: "
                       f"{', '.join(f'{a}/{b}' for a, b in TARGETS)}") from None
