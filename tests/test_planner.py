import json
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

from trueup import planner
from trueup.model import (CHEAP_MODEL, PLAN_MODEL, ModelClient, ModelError, SpendLimitReached, get_spend,
                          parse_json, proxy_root, record_spend)
from trueup.scenarios import get
from trueup.scenarios import proposed as prop
from trueup.sweep import sweep

GOOD = {
    "id": "p-chat-stream-usage-tools", "provider": "openai", "api": "chat", "framework": "none",
    "does": "Streams two tool calls with include_usage.", "app": "chat_stream_usage", "model": "chat-tools",
    "expected": {"calls": 1, "outcome": "ok", "fake": ["complete"], "tokens": [{"input": 11, "output": 7}],
                 "tool_calls": [["get_weather", "get_time"]]},
}


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def spend_get(spend, calls=None):
    def get(url, headers=None, timeout=None):
        if calls is not None:
            calls.append((url, headers))
        return FakeResp(200, {"info": {"spend": spend}})
    return get


class FakeOpenAI:
    """Stands in for openai.OpenAI: replies are strings, or exceptions to raise."""

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.sent.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content=r))])


def client(replies, spend=0.0, calls=None):
    return ModelClient("k-test", "http://proxy.test/v1", http_get=spend_get(spend, calls),
                       openai_client=FakeOpenAI(replies), sleep=lambda s: None)


def conn_error():
    return openai.APIConnectionError(request=__import__("httpx").Request("POST", "http://proxy.test"))


# --- model client and spending guard


def test_proxy_root_strips_v1():
    assert proxy_root("https://p.example/v1/") == "https://p.example"
    assert proxy_root("https://p.example") == "https://p.example"


def test_guard_reads_key_info_with_bearer():
    calls = []
    assert get_spend("http://proxy.test/v1", "k-test", spend_get(3.5, calls)) == 3.5
    assert calls == [("http://proxy.test/key/info", {"Authorization": "Bearer k-test"})]


@pytest.mark.parametrize("spend", [15.0, 15.01, 99])
def test_guard_refuses_at_or_over_limit(spend):
    c = client(["{}"], spend=spend)
    with pytest.raises(SpendLimitReached, match="spend limit reached"):
        c.chat(PLAN_MODEL, [{"role": "user", "content": "hi"}])
    assert c.client.sent == []  # no model call made


def test_guard_allows_under_limit():
    c = client(['{"ok": 1}'], spend=14.99)
    assert c.chat_json(CHEAP_MODEL, [{"role": "user", "content": "hi"}]) == {"ok": 1}
    assert c.usage.calls == 1 and c.usage.input_tokens == 100


def test_guard_unreadable_spend_stops():
    c = ModelClient("k", "http://proxy.test/v1", http_get=lambda *a, **k: FakeResp(500),
                    openai_client=FakeOpenAI(["{}"]))
    with pytest.raises(ModelError, match="HTTP 500"):
        c.chat(PLAN_MODEL, [])
    c = ModelClient("k", "http://proxy.test/v1", http_get=lambda *a, **k: FakeResp(200, {"x": 1}),
                    openai_client=FakeOpenAI(["{}"]))
    with pytest.raises(ModelError, match="info.spend"):
        c.chat(PLAN_MODEL, [])


def test_no_opus():
    with pytest.raises(ModelError, match="opus"):
        client(["{}"]).chat("claude-opus-4.6", [])


def test_retries_with_backoff_then_succeeds():
    slept = []
    c = ModelClient("k", "http://proxy.test/v1", http_get=spend_get(0), sleep=slept.append, backoff=1,
                    openai_client=FakeOpenAI([conn_error(), conn_error(), "hello"]))
    assert c.chat(PLAN_MODEL, []) == "hello"
    assert slept == [1, 2]


def test_retries_give_up():
    c = client([conn_error()] * 4)
    with pytest.raises(ModelError, match="after 4 tries: APIConnectionError"):
        c.chat(PLAN_MODEL, [])


def test_invalid_json_retried_then_stops():
    c = client(["not json", '```json\n{"a": 1}\n```'])
    assert c.chat_json(PLAN_MODEL, []) == {"a": 1}
    assert "not valid JSON" in c.client.sent[1]["messages"][-1]["content"]
    c = client(["nope", "nope", "nope"])
    with pytest.raises(ModelError, match="invalid JSON 3 times"):
        c.chat_json(PLAN_MODEL, [])


def test_parse_json_fence():
    assert parse_json('```\n[1]\n```') == [1]


def test_record_spend_before_after(tmp_path):
    c = client(["x"])
    record_spend(tmp_path, "before", c)
    c.chat(PLAN_MODEL, [])
    c.http_get = spend_get(0.25)
    record_spend(tmp_path, "after", c)
    d = json.loads((tmp_path / "spend.json").read_text())
    assert d["before"]["spend_usd"] == 0.0 and d["after"]["spend_usd"] == 0.25
    assert d["run_cost_usd"] == 0.25 and d["usage"]["calls"] == 1
    assert "k-test" not in (tmp_path / "spend.json").read_text()


# --- proposal validation


def test_good_proposal_passes_schema():
    assert prop.validate(GOOD) == []


@pytest.mark.parametrize("change,reason", [
    ({"app": "make_coffee"}, "unknown app"),
    ({"model": "chat-teapot"}, "not supported on /v1/chat/completions"),
    ({"model": "resp-plain"}, "not supported"),
    ({"api": "responses"}, "app chat_stream_usage is provider=openai api=chat"),
    ({"app": "chat_create", "model": "chat-plain"}, "already a scenario"),
    ({"id": "oa-chat-plain"}, "must look like"),
    ({"expected": {"calls": 1, "outcome": "ok"}}, "must name fake"),
    ({"expected": {"calls": 1, "outcome": "ok", "fake": ["complete"], "cost": 1}}, "cannot check: cost"),
    ({"expected": {"calls": 2, "outcome": "ok", "fake": ["complete"]}}, "expected.fake must be a list"),
    ({"expected": {"calls": 1, "outcome": "exception", "fake": ["cut"]}}, "expected.exception"),
    ({"code": "import os"}, "unknown fields: code"),
])
def test_bad_proposals_rejected_with_reason(change, reason):
    errs = prop.validate({**GOOD, **change})
    assert any(reason in e for e in errs), errs


def test_untraced_check_runs_real_sdk():
    diffs, t = prop.untraced_check(GOOD)
    assert diffs == [] and t["include_usage"] == [True]
    wrong = {**GOOD, "expected": {**GOOD["expected"], "tokens": [None]}}
    diffs, _ = prop.untraced_check(wrong)
    assert diffs == ['expected.tokens is [null] but the untraced run gives [{"input": 11, "output": 7}]']


def test_untraced_check_uses_child_env(monkeypatch):
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-secret")
    seen = {}

    def fake_run(cmd, env, **kw):
        seen.update(env)
        return SimpleNamespace(returncode=0, stdout=json.dumps(GOOD["expected"]), stderr="")
    monkeypatch.setattr(prop.subprocess, "run", fake_run)
    prop.untraced_check(GOOD)
    assert "NEATLOGS_API_KEY" not in seen and seen["NEATLOGS_DISABLE_EXPORT"] == "true"


# --- planner


@pytest.fixture
def proposed_dir(tmp_path, monkeypatch):
    d = tmp_path / "proposed"
    monkeypatch.setenv("TRUEUP_PROPOSED_DIR", str(d))
    return d


def fake_root(tmp_path):
    site = tmp_path / ".trueup/venvs/neatlogs/lib/python3.12/site-packages/neatlogs"
    site.mkdir(parents=True)
    (site / "openai.py").write_text("def wrap(): pass\n")
    return tmp_path


def test_planner_accepts_revises_and_rejects(tmp_path, proposed_dir):
    root = fake_root(tmp_path)
    bad_app = {**GOOD, "id": "p-bad-app", "app": "make_coffee"}
    bad_twice = {**GOOD, "id": "p-bad-model", "app": "chat_create", "model": "chat-teapot"}
    fixed = {**GOOD, "id": "p-fixed", "app": "chat_stream", "model": "chat-tools",
             "expected": {"calls": 1, "outcome": "ok", "fake": ["complete"]}}
    replies = [
        json.dumps({"proposals": [GOOD, bad_app, bad_twice]}),
        json.dumps({"proposals": [fixed]}),  # revision of bad_app
        json.dumps({"proposals": [bad_twice]}),  # revision 1 of bad_twice, still bad
        json.dumps({"proposals": [bad_twice]}),  # revision 2, still bad
    ]
    c = client(replies)
    res = planner.plan(root, "neatlogs", 3, client=c, run_id="r-plan", out=lambda s: None,
                       untraced=lambda p: ([], None))
    assert [a["id"] for a in res["accepted"]] == ["p-chat-stream-usage-tools", "p-fixed"]
    assert res["accepted"][1]["revisions"] == 1
    assert len(res["rejected"]) == 1 and res["rejected"][0]["tries"] == 3
    assert "not supported" in res["rejected"][0]["reasons"][0]
    assert len(c.client.sent) == 4  # first plan + 1 + 2 revisions, never more
    assert "make_coffee" in c.client.sent[1]["messages"][1]["content"]  # the reason went back
    assert sorted(p.name for p in (proposed_dir / "neatlogs").iterdir()) == [
        "p-chat-stream-usage-tools.json", "p-fixed.json"]
    plan_json = json.loads((root / ".trueup/runs/r-plan/plan.json").read_text())
    assert plan_json["usage"]["calls"] == 4
    assert json.loads((root / ".trueup/runs/r-plan/spend.json").read_text())["run_cost_usd"] == 0.0
    # Accepted proposals load as scenarios, also by id.
    assert get("p-fixed").app == "chat_stream"


def test_planner_rejects_truth_the_untraced_run_disagrees_with(tmp_path, proposed_dir):
    c = client([json.dumps({"proposals": [GOOD]}), '{"proposals": []}'])
    res = planner.plan(fake_root(tmp_path), "neatlogs", 1, client=c, run_id="r", out=lambda s: None,
                       untraced=lambda p: (["expected.calls is 1 but the untraced run gives 2"], None))
    assert res["accepted"] == [] and "withdrawn by the model" in res["rejected"][0]["reasons"][0]


def test_planner_stops_on_invalid_json(tmp_path, proposed_dir):
    res = planner.plan(fake_root(tmp_path), "neatlogs", 1, client=client(["x", "y", "z"]), run_id="r",
                       out=lambda s: None)
    assert "invalid JSON" in res["error"] and res["accepted"] == []


def test_planner_stops_at_spend_limit(tmp_path, proposed_dir):
    c = client(["{}"], spend=15.0)
    res = planner.plan(fake_root(tmp_path), "neatlogs", 1, client=c, run_id="r", out=lambda s: None)
    assert "spend limit reached" in res["error"] and c.client.sent == []


def test_sweep_proposed(tmp_path, proposed_dir):
    prop.save(GOOD, "neatlogs")
    seen = []

    def run(py, lib, sid):
        seen.append(sid)
        return {"scenario": sid, "library": lib, "status": "not_run", "reason": "stub", "seconds": 0,
                "observation": None}
    run_dir, results = sweep(tmp_path, "openllmetry", proposed="neatlogs", ensure=lambda r, l: Path("/py"),
                             run=run, out=lambda s: None)
    assert seen == ["p-chat-stream-usage-tools"] and run_dir.name.endswith("-openllmetry-proposed")
