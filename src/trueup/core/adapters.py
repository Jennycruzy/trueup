"""Where each tracing library keeps the facts the comparer needs. Pure, data-driven.

One Adapter per library. Each names the attribute keys (or key patterns) for:
which spans are LLM calls, tokens, finish reasons, output text, refusals and
tool calls. Two shapes exist: flat attributes with numeric indexes
(neatlogs, OpenInference) and one JSON attribute holding the output messages
(OpenLLMetry's gen_ai.output.messages).

Adding a library means adding one Adapter here, not changing the comparer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# Finish reasons with the same meaning, mapped to one name. OpenLLMetry
# normalises to the OTel GenAI names (stop, tool_call, length); the providers
# and the other libraries keep the raw ones.
FINISH_SYNONYMS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "completed": "stop",
    "tool_calls": "tool_call",
    "tool_use": "tool_call",
    "function_call": "tool_call",
    "max_tokens": "length",
    "incomplete": "length",
}


def norm_finish(value: str | None) -> str | None:
    return None if value is None else FINISH_SYNONYMS.get(value, value)


@dataclass(frozen=True)
class Adapter:
    library: str
    # A span is an LLM call if attributes[key] is in values (any value if values is empty)
    # and no llm_exclude rule matches (same shape).
    llm_kind: tuple[str, tuple[str, ...]]
    input_tokens: tuple[str, ...]
    output_tokens: tuple[str, ...]
    response_id: tuple[str, ...] = ()
    # Keys whose value is one finish reason or a list of them; regexes match indexed keys.
    finish: tuple[str, ...] = ()
    # Flat shape: regexes over attribute keys. Tool name/arguments regexes have
    # one group per index, used to pair a name with its arguments.
    text: tuple[str, ...] = ()
    refusal: tuple[str, ...] = ()
    tool_name: tuple[str, ...] = ()
    tool_args: tuple[str, ...] = ()
    # JSON shape: one attribute with a list of {"parts": [{"type", "content"|"name"|"arguments"}]}.
    messages_json: str | None = None
    llm_exclude: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Tool spans (framework runs): same rule shape as llm_kind, and where the tool name is.
    tool_kind: tuple[str, tuple[str, ...]] | None = None
    tool_span_name: tuple[str, ...] = ()


NEATLOGS = Adapter(
    library="neatlogs",
    llm_kind=("neatlogs.span.kind", ("llm",)),
    input_tokens=("neatlogs.llm.token_count.prompt",),
    output_tokens=("neatlogs.llm.token_count.completion",),
    response_id=("neatlogs.llm.response_id",),
    finish=(r"neatlogs\.llm\.finish_reason", r"neatlogs\.llm\.choices\.\d+\.finish_reason"),
    text=(r"neatlogs\.llm\.output_messages\.\d+\.content",),
    refusal=(r"neatlogs\.llm\.output_messages\.\d+\.refusal",),
    tool_name=(r"neatlogs\.llm\.tool_calls\.(\d+)\.name",),
    tool_args=(r"neatlogs\.llm\.tool_calls\.(\d+)\.arguments",),
    tool_kind=("neatlogs.span.kind", ("tool",)),
    tool_span_name=("neatlogs.tool.name", "tool.name"),
)

OPENINFERENCE = Adapter(
    library="openinference",
    llm_kind=("openinference.span.kind", ("LLM",)),
    input_tokens=("llm.token_count.prompt",),
    output_tokens=("llm.token_count.completion",),
    finish=(r"llm\.finish_reason",),
    text=(
        r"llm\.output_messages\.\d+\.message\.content",
        r"llm\.output_messages\.\d+\.message\.contents\.\d+\.message_content\.text",
    ),
    refusal=(r"llm\.output_messages\.\d+\.message\.refusal",),
    tool_name=(r"llm\.output_messages\.(\d+\.message\.tool_calls\.\d+)\.tool_call\.function\.name",),
    tool_args=(r"llm\.output_messages\.(\d+\.message\.tool_calls\.\d+)\.tool_call\.function\.arguments",),
    tool_kind=("openinference.span.kind", ("TOOL",)),
    tool_span_name=("tool.name",),
)

OPENLLMETRY = Adapter(
    library="openllmetry",
    # Error spans for failed streams carry no gen_ai.operation.name, so key on the provider.
    # Framework spans carry a provider too (langgraph, openai): agent, task, tool and workflow
    # spans are told apart by their operation name or traceloop.span.kind.
    llm_kind=("gen_ai.provider.name", ()),
    llm_exclude=(
        ("gen_ai.operation.name", ("create_agent", "invoke_agent", "execute_task", "execute_tool")),
        ("traceloop.span.kind", ()),
    ),
    tool_kind=("traceloop.span.kind", ("tool",)),
    tool_span_name=("gen_ai.tool.name",),
    input_tokens=("gen_ai.usage.input_tokens",),
    output_tokens=("gen_ai.usage.output_tokens",),
    response_id=("gen_ai.response.id",),
    finish=(r"gen_ai\.response\.finish_reasons",),
    messages_json="gen_ai.output.messages",
)

ADAPTERS: dict[str, Adapter] = {a.library: a for a in (NEATLOGS, OPENINFERENCE, OPENLLMETRY)}

# Reasoning text is not output text. OpenInference marks it per content part.
_OI_REASONING = re.compile(r"(llm\.output_messages\.\d+\.message\.contents\.\d+)\.message_content\.text")


@dataclass(frozen=True)
class SpanFacts:
    """What one LLM span says, in the comparer's terms."""

    input_tokens: int | None
    output_tokens: int | None
    response_id: str | None
    finish: tuple[str, ...]
    texts: tuple[str, ...]
    refusals: tuple[str, ...]
    tool_calls: tuple[tuple[str, Any], ...]  # (name, arguments as recorded)


def _first(attrs: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if attrs.get(k) is not None:
            return attrs[k]
    return None


def _matching(attrs: dict[str, Any], patterns: tuple[str, ...]) -> list[tuple[re.Match[str], Any]]:
    out = []
    for p in patterns:
        rx = re.compile(p)
        out += [(m, v) for k, v in attrs.items() if (m := rx.fullmatch(k))]
    return out


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rule(rule: tuple[str, tuple[str, ...]], attrs: dict[str, Any]) -> bool:
    key, values = rule
    v = attrs.get(key)
    return v is not None and (not values or v in values)


def is_llm_span(adapter: Adapter, span: dict[str, Any]) -> bool:
    attrs = span.get("attributes", {})
    return _rule(adapter.llm_kind, attrs) and not any(_rule(r, attrs) for r in adapter.llm_exclude)


def tool_span_name(adapter: Adapter, span: dict[str, Any]) -> str | None:
    """The tool's name if this is a tool span, else None."""
    attrs = span.get("attributes", {})
    if adapter.tool_kind is None or not _rule(adapter.tool_kind, attrs):
        return None
    name = _first(attrs, adapter.tool_span_name)
    return name if isinstance(name, str) else span.get("name")


def _flat_outputs(adapter: Adapter, attrs: dict[str, Any]) -> tuple[list[str], list[str], list[tuple[str, Any]]]:
    texts = []
    for m, v in _matching(attrs, adapter.text):
        rm = _OI_REASONING.fullmatch(m.group(0))
        if rm and attrs.get(f"{rm.group(1)}.message_content.type") == "reasoning":
            continue
        if isinstance(v, str):
            texts.append(v)
    refusals = [v for _, v in _matching(attrs, adapter.refusal) if isinstance(v, str)]
    args = {m.group(1): v for m, v in _matching(attrs, adapter.tool_args)}
    tools = [(v, args.get(m.group(1))) for m, v in _matching(attrs, adapter.tool_name)]
    return texts, refusals, tools


def _json_outputs(raw: Any) -> tuple[list[str], list[str], list[tuple[str, Any]]]:
    texts: list[str] = []
    refusals: list[str] = []
    tools: list[tuple[str, Any]] = []
    try:
        messages = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        return texts, refusals, tools
    for msg in messages if isinstance(messages, list) else []:
        for part in (msg or {}).get("parts", []) if isinstance(msg, dict) else []:
            kind = part.get("type")
            if kind == "text" and isinstance(part.get("content"), str):
                texts.append(part["content"])
            elif kind == "refusal" and isinstance(part.get("content"), str):
                refusals.append(part["content"])
            elif kind == "tool_call":
                tools.append((part.get("name"), part.get("arguments")))
    return texts, refusals, tools


def _finish(adapter: Adapter, attrs: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for _, v in _matching(attrs, adapter.finish):
        for x in v if isinstance(v, list) else [v]:
            if isinstance(x, str) and x:
                out.append(x)
    return tuple(out)


def facts(adapter: Adapter, span: dict[str, Any]) -> SpanFacts:
    attrs = span.get("attributes", {})
    if adapter.messages_json:
        texts, refusals, tools = _json_outputs(attrs.get(adapter.messages_json))
    else:
        texts, refusals, tools = _flat_outputs(adapter, attrs)
    rid = _first(attrs, adapter.response_id)
    return SpanFacts(
        input_tokens=_int(_first(attrs, adapter.input_tokens)),
        output_tokens=_int(_first(attrs, adapter.output_tokens)),
        response_id=rid if isinstance(rid, str) else None,
        finish=_finish(adapter, attrs),
        texts=tuple(texts),
        refusals=tuple(refusals),
        tool_calls=tuple(tools),
    )
