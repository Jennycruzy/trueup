"""Regression tests for traps hit while building the earlier harness."""

import asyncio
import inspect

import openai
import pytest

from trueup.fake import FakeProvider
from trueup.runner import apps, framework_apps, setups
from trueup.runner.run import child_env
from trueup.scenarios import library as lib

M = [{"role": "user", "content": "hi"}]


# Trap 1: two scenarios reusing a response id made a library skip a span.


def test_response_ids_unique_across_calls_and_apis():
    with FakeProvider() as f:
        oc = openai.OpenAI(api_key="x", base_url=f.openai_base_url, max_retries=0)
        for _ in range(3):
            oc.chat.completions.create(model="chat-plain", messages=M)
            oc.responses.create(model="resp-plain", input="hi")
            list(oc.chat.completions.create(model="chat-plain", messages=M, stream=True))
        ids = [e["response_id"] for e in f.log.entries()]
    assert len(ids) == 9 and len(set(ids)) == 9


def test_response_ids_unique_across_fake_instances():
    seen = []
    for _ in range(2):
        with FakeProvider() as f:
            oc = openai.OpenAI(api_key="x", base_url=f.openai_base_url, max_retries=0)
            seen.append(oc.chat.completions.create(model="chat-plain", messages=M).id)
    # Each scenario runs in its own fake; the per-instance token keeps ids apart.
    assert seen[0] != seen[1]


def test_every_built_scenario_run_gets_its_own_ids():
    ids = []
    for s in lib.SCENARIOS:
        with FakeProvider() as f:
            try:
                apps.APPS[s.app](f.base_url, s.model)
            except Exception:
                pass
            ids += [e["response_id"] for e in f.log.entries() if e["response_id"]]
    assert len(ids) == len(set(ids))


# Trap 2: one async client reused across asyncio.run loops gives "Event loop is closed".


def test_reused_async_client_across_loops_fails():
    # Documents the trap: this is what the apps must not do.
    with FakeProvider() as f:
        c = openai.AsyncOpenAI(api_key="x", base_url=f.openai_base_url, max_retries=0)

        async def call():
            return await c.chat.completions.create(model="chat-plain", messages=M)

        asyncio.run(call())
        with pytest.raises(RuntimeError, match="Event loop is closed"):
            asyncio.run(call())


@pytest.mark.parametrize("app,model", [
    ("chat_async_stream", "chat-plain"),
    ("an_async_create", "anth-plain"),
    # The Agents SDK runs each Runner call in a new loop; the apps give each agent its own client.
    ("ag_run", "agent-resp"),
    ("ag_run_streamed", "agent-resp"),
])
def test_async_apps_survive_repeated_asyncio_run(app, model):
    with FakeProvider() as f:
        first = apps.APPS[app](f.base_url, model)
        second = apps.APPS[app](f.base_url, model)
    assert first == second


@pytest.mark.parametrize("module", [apps, framework_apps])
def test_apps_module_keeps_no_client_at_module_level(module):
    src = inspect.getsource(module)
    top_level = [ln for ln in src.splitlines() if ln and not ln[0].isspace()]
    assert not any("OpenAI(" in ln or "Anthropic(" in ln or "set_default_openai_client" in ln for ln in top_level)


# Trap 3: a fake that sends no usage makes missing tokens look like a bug.


def test_stream_without_include_usage_records_tokens_as_not_sent():
    with FakeProvider() as f:
        apps.chat_stream(f.base_url, "chat-plain")
        (e,) = f.log.entries()
    assert e["usage"] is None and e["usage_sent"] is False


def test_scenarios_expect_no_tokens_only_where_fake_sends_none():
    # Expected tokens must come from what the fake really sent, so a trace
    # without tokens is only a bug when the fake did send them.
    s = lib.get("oa-chat-stream-no-usage")
    assert s.expected["tokens"] == [None]
    assert lib.get("oa-chat-stream-usage").expected["tokens"] == [lib.OA_TOK]


def test_fake_sends_usage_for_every_complete_reply_that_has_it():
    with FakeProvider() as f:
        apps.chat_create(f.base_url, "chat-plain")
        apps.chat_stream_usage(f.base_url, "chat-plain")
        apps.resp_stream(f.base_url, "resp-plain")
        apps.an_stream_helper(f.base_url, "anth-plain")
        entries = f.log.entries()
    assert all(e["usage_sent"] and e["usage"]["total_tokens"] > 0 for e in entries)


# Trap 4: neatlogs exporting to a dead endpoint made one run take 200 s.


def test_neatlogs_setup_disables_export_and_sets_no_endpoint():
    kw = setups.neatlogs_init_kwargs(tracer_provider=object())
    assert kw["disable_export"] is True
    assert "endpoint" not in kw
    assert kw["api_key"] == "trueup-fake"


def test_child_env_disables_export_and_drops_real_keys():
    env = child_env({"NEATLOGS_API_KEY": "real", "NEATLOGS_ENDPOINT": "http://127.0.0.1:9", "PATH": "/bin"})
    assert env["NEATLOGS_DISABLE_EXPORT"] == "true"
    assert "NEATLOGS_API_KEY" not in env and "NEATLOGS_ENDPOINT" not in env
    assert env["OTEL_TRACES_EXPORTER"] == "none"
    assert env["TRACELOOP_TELEMETRY"] == "false"
