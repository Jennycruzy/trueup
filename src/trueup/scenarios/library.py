"""The scenario library, as data.

Each scenario names the fake model it calls (the fake picks its behaviour from
the model name), the app code that drives it (`app`, a function in
trueup.runner.apps), and the truth fields we expect the run to produce.

Expected truth keys (only the ones listed are checked):
  calls       number of requests the fake received
  outcome     "ok" or "exception" (what the app saw)
  exception   exception class name, when outcome is "exception"
  tokens      per call: {"input": n, "output": n}, or None when the fake sent no usage
  finish      per call: finish/stop reason or response status
  tool_calls  per call: tool names the model asked for
  fake        per call: what the fake did (complete, failed, incomplete, error_event, cut, http_error)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BUILT = "built"
NOT_BUILT = "not_built"

OA_TOK = {"input": 11, "output": 7}
AN_TOK = {"input": 5, "output": 3}


@dataclass(frozen=True)
class Scenario:
    id: str
    provider: str  # openai, anthropic
    api: str  # chat, responses, messages
    framework: str  # none, langchain, langgraph, openai-agents
    does: str  # what the app does, in plain words
    app: str  # function name in trueup.runner.apps
    model: str  # fake scenario, sent as the model name
    expected: dict[str, Any] = field(default_factory=dict)
    status: str = BUILT

    @property
    def plain_sdk(self) -> bool:
        return self.framework == "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "api": self.api,
            "framework": self.framework,
            "does": self.does,
            "app": self.app,
            "model": self.model,
            "expected": self.expected,
            "status": self.status,
        }


def _ok(tokens: Any, finish: Any, tools: Any = None, calls: int = 1, fake: str = "complete") -> dict[str, Any]:
    return {
        "calls": calls,
        "outcome": "ok",
        "tokens": [tokens] * calls,
        "finish": [finish] * calls,
        "tool_calls": [tools or []] * calls,
        "fake": [fake] * calls,
    }


def _raises(exc: str, fake: str) -> dict[str, Any]:
    return {"calls": 1, "outcome": "exception", "exception": exc, "tokens": [None], "fake": [fake]}


def _s(id: str, provider: str, api: str, does: str, app: str, model: str, expected: dict[str, Any]) -> Scenario:
    return Scenario(id, provider, api, "none", does, app, model, expected)


SCENARIOS: tuple[Scenario, ...] = (
    # OpenAI Chat Completions
    _s("oa-chat-plain", "openai", "chat", "One chat call, reads the text.", "chat_create", "chat-plain",
       _ok(OA_TOK, ["stop"])),
    _s("oa-chat-stream-usage", "openai", "chat", "Streams a chat reply with include_usage.", "chat_stream_usage", "chat-plain",
       _ok(OA_TOK, ["stop"])),
    _s("oa-chat-stream-no-usage", "openai", "chat",
       "Streams a chat reply without include_usage. The fake sends no usage, so tokens are unknown, not zero.",
       "chat_stream", "chat-plain", _ok(None, ["stop"])),
    _s("oa-chat-tools", "openai", "chat", "One call that returns two parallel tool calls.", "chat_create_tools", "chat-tools",
       _ok(OA_TOK, ["tool_calls"], ["get_weather", "get_time"])),
    _s("oa-chat-stream-tools", "openai", "chat",
       "Streams two parallel tool calls whose arguments arrive split and interleaved.",
       "chat_stream_tools", "chat-tools", _ok(None, ["tool_calls"], ["get_weather", "get_time"])),
    _s("oa-chat-refusal", "openai", "chat", "The model refuses; content is null, refusal is set.", "chat_create", "chat-refusal",
       _ok(OA_TOK, ["stop"])),
    _s("oa-chat-n2", "openai", "chat", "Asks for n=2 choices and reads both.", "chat_create_n2", "chat-n2",
       _ok(OA_TOK, ["stop", "stop"])),
    _s("oa-chat-500", "openai", "chat", "The provider returns HTTP 500; the app gets an exception.", "chat_create", "chat-500",
       _raises("InternalServerError", "http_error")),
    _s("oa-chat-stream-error-event", "openai", "chat", "An error event arrives mid-stream.", "chat_stream", "chat-error-event",
       _raises("APIError", "error_event")),
    _s("oa-chat-stream-cut", "openai", "chat", "The connection drops mid-stream.", "chat_stream", "chat-cut",
       _raises("APIConnectionError", "cut")),
    _s("oa-chat-stream-break", "openai", "chat", "The app stops reading after the first chunk and closes the stream.",
       "chat_stream_break", "chat-plain", _ok(None, ["stop"])),
    _s("oa-chat-async-stream", "openai", "chat", "Async client, streamed with include_usage, inside asyncio.run.",
       "chat_async_stream", "chat-plain", _ok(OA_TOK, ["stop"])),
    # OpenAI Responses
    _s("oa-resp-plain", "openai", "responses", "One Responses call, reads output_text.", "resp_create", "resp-plain",
       _ok(OA_TOK, ["completed"])),
    _s("oa-resp-tool", "openai", "responses", "Returns one function call.", "resp_create", "resp-tool",
       _ok(OA_TOK, ["completed"], ["get_weather"])),
    _s("oa-resp-reasoning", "openai", "responses", "Returns a reasoning summary and a message; 4 reasoning tokens.",
       "resp_create", "resp-reasoning", _ok(OA_TOK, ["completed"])),
    _s("oa-resp-failed", "openai", "responses", "Response comes back with status failed (HTTP 200, no exception).",
       "resp_create", "resp-failed", _ok(None, ["failed"], fake="failed")),
    _s("oa-resp-incomplete", "openai", "responses", "Response comes back incomplete (max_output_tokens).",
       "resp_create", "resp-incomplete", _ok(OA_TOK, ["incomplete"], fake="incomplete")),
    _s("oa-resp-stream", "openai", "responses", "Streams a Responses call with the stream helper.", "resp_stream", "resp-plain",
       _ok(OA_TOK, ["completed"])),
    _s("oa-resp-stream-tool", "openai", "responses", "Streams a function call with split arguments.", "resp_stream", "resp-tool",
       _ok(OA_TOK, ["completed"], ["get_weather"])),
    _s("oa-resp-stream-error-event", "openai", "responses",
       "An error event arrives mid-stream. The SDK hands it to the app; the app raises RuntimeError.",
       "resp_stream_raw", "resp-error-event", _raises("RuntimeError", "error_event")),
    _s("oa-resp-stream-cut", "openai", "responses", "The connection drops mid-stream.", "resp_stream_raw", "resp-cut",
       _raises("APIConnectionError", "cut")),
    # Anthropic Messages
    _s("an-plain", "anthropic", "messages", "One messages call, reads the text.", "an_create", "anth-plain",
       _ok(AN_TOK, ["end_turn"])),
    _s("an-thinking", "anthropic", "messages", "Reply has a thinking block and a text block.", "an_create", "anth-thinking",
       _ok(AN_TOK, ["end_turn"])),
    _s("an-stream-helper", "anthropic", "messages", "Uses messages.stream, reads text_stream and the final message.",
       "an_stream_helper", "anth-plain", _ok(AN_TOK, ["end_turn"])),
    _s("an-stream-thinking", "anthropic", "messages", "Streams thinking then text.", "an_stream_helper", "anth-thinking",
       _ok(AN_TOK, ["end_turn"])),
    _s("an-stream-tools", "anthropic", "messages", "Streams a tool_use block built from input_json_delta.",
       "an_stream_helper_tools", "anth-tools", _ok(AN_TOK, ["tool_use"], ["get_weather"])),
    _s("an-create-stream", "anthropic", "messages", "messages.create(stream=True), reads raw events.", "an_create_stream",
       "anth-plain", _ok(AN_TOK, ["end_turn"])),
    _s("an-stream-error-event", "anthropic", "messages", "An error event arrives mid-stream.", "an_create_stream",
       "anth-error-event", _raises("APIStatusError", "error_event")),
    _s("an-stream-cut", "anthropic", "messages",
       "The connection drops mid-stream. The anthropic SDK lets the transport error through.",
       "an_create_stream", "anth-cut", _raises("RemoteProtocolError", "cut")),
    _s("an-529", "anthropic", "messages", "The provider returns 529 overloaded.", "an_create", "anth-529",
       _raises("OverloadedError", "http_error")),
    _s("an-async", "anthropic", "messages", "Async client inside asyncio.run.", "an_async_create", "anth-plain",
       _ok(AN_TOK, ["end_turn"])),
)


def _fw(id: str, framework: str, does: str) -> Scenario:
    return Scenario(id, "openai", "chat" if framework.startswith("lang") else "responses", framework, does, "", "",
                    status=NOT_BUILT)


# Framework cases from the earlier harness. Listed so the gap is visible; not built yet.
FRAMEWORK_SCENARIOS: tuple[Scenario, ...] = (
    _fw("lc-invoke", "langchain", "ChatOpenAI.invoke, one call."),
    _fw("lc-stream", "langchain", "ChatOpenAI.stream with stream_usage."),
    _fw("lc-stream-error-event", "langchain", "Error event mid-stream through ChatOpenAI."),
    _fw("lc-stream-cut", "langchain", "Dropped connection mid-stream through ChatOpenAI."),
    _fw("lc-refusal", "langchain", "Refusal surfaced through additional_kwargs."),
    _fw("lc-500", "langchain", "HTTP 500 through ChatOpenAI."),
    _fw("lg-agent", "langgraph", "ReAct agent: tool call, then answer (2 LLM calls)."),
    _fw("lg-tool-raises", "langgraph", "A tool raises inside the agent."),
    _fw("lg-llm-fails", "langgraph", "Second LLM call returns 500."),
    _fw("lg-parallel", "langgraph", "Two parallel tool calls in one step."),
    _fw("lg-stream", "langgraph", "Agent run streamed."),
    _fw("lg-recursion", "langgraph", "Agent loops until the recursion limit."),
    _fw("ag-run", "openai-agents", "Runner.run_sync: tool call, then answer."),
    _fw("ag-tool-raises", "openai-agents", "A function tool raises."),
    _fw("ag-llm-fails", "openai-agents", "Second model call returns 500."),
    _fw("ag-max-turns", "openai-agents", "Agent hits max_turns."),
    _fw("ag-bad-tool", "openai-agents", "Model calls a tool that does not exist."),
    _fw("ag-streamed", "openai-agents", "Runner.run_streamed, ok."),
    _fw("ag-streamed-error", "openai-agents", "Error event in the second streamed call."),
    _fw("ag-streamed-cut", "openai-agents", "Dropped connection in the second streamed call."),
)

ALL: tuple[Scenario, ...] = SCENARIOS + FRAMEWORK_SCENARIOS
_BY_ID = {s.id: s for s in ALL}


def get(scenario_id: str) -> Scenario:
    try:
        return _BY_ID[scenario_id]
    except KeyError:
        raise KeyError(f"unknown scenario {scenario_id!r}") from None


def plain_sdk() -> list[Scenario]:
    return [s for s in ALL if s.plain_sdk]
