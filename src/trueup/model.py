"""The one model client: the openai SDK against an OpenAI-compatible LiteLLM proxy.

Every call first asks the proxy what the key has spent (GET <base>/key/info) and
refuses to call at or above SPEND_LIMIT. The key and base URL come from
TRUEUP_MODEL_KEY and TRUEUP_MODEL_BASE_URL and are never printed or written.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

PLAN_MODEL = "claude-sonnet-4.6"  # planning and fixing
CHEAP_MODEL = "claude-haiku"  # cheap jobs
SPEND_LIMIT = 15.0  # USD, from the key's spend on the proxy
KEY_VAR, BASE_VAR = "TRUEUP_MODEL_KEY", "TRUEUP_MODEL_BASE_URL"


class ModelError(RuntimeError):
    """The model could not give a usable answer. Stops the worker that asked."""


class SpendLimitReached(ModelError):
    """The key has spent SPEND_LIMIT or more. No call is made."""


def check_model(name: str) -> str:
    if "opus" in name.lower():
        raise ModelError(f"model {name!r} is not allowed (no opus models)")
    return name


def proxy_root(base_url: str) -> str:
    """The proxy's root: the base URL without a trailing /v1."""
    b = base_url.rstrip("/")
    return b[: -len("/v1")] if b.endswith("/v1") else b


def get_spend(base_url: str, key: str, http_get: Callable[..., Any] = httpx.get) -> float:
    """The key's spend in USD, read from info.spend of GET <root>/key/info."""
    r = http_get(proxy_root(base_url) + "/key/info", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    if r.status_code != 200:
        raise ModelError(f"could not read the key's spend: HTTP {r.status_code}")
    try:
        return float(r.json()["info"]["spend"] or 0.0)
    except (KeyError, TypeError, ValueError) as e:
        raise ModelError(f"could not read the key's spend: no info.spend in the reply ({type(e).__name__})") from None


def guard(spend: float, limit: float = SPEND_LIMIT) -> None:
    if spend >= limit:
        raise SpendLimitReached(f"spend limit reached: the key has spent ${spend:.4f}, limit ${limit:.2f}. "
                                "No model call made.")


def parse_json(text: str) -> Any:
    """JSON from a model reply; a ```json fence around it is allowed."""
    t = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    return json.loads(m.group(1) if m else t)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, model: str, inp: int, out: int) -> None:
        self.calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        m = self.by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        m["calls"] += 1
        m["input_tokens"] += inp
        m["output_tokens"] += out

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "by_model": self.by_model}


class ModelClient:
    def __init__(self, key: str | None = None, base_url: str | None = None, *, limit: float = SPEND_LIMIT,
                 retries: int = 3, json_retries: int = 2, backoff: float = 2.0,
                 http_get: Callable[..., Any] = httpx.get, openai_client: Any = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.key = key or os.environ.get(KEY_VAR) or ""
        self.base_url = base_url or os.environ.get(BASE_VAR) or ""
        if not self.key or not self.base_url:
            raise ModelError(f"{KEY_VAR} and {BASE_VAR} must be set")
        self.limit, self.retries, self.json_retries, self.backoff = limit, retries, json_retries, backoff
        self.http_get, self.sleep = http_get, sleep
        self.usage = Usage()
        if openai_client is None:
            import openai

            openai_client = openai.OpenAI(api_key=self.key, base_url=self.base_url, max_retries=0, timeout=180)
        self.client = openai_client

    def spend(self) -> float:
        return get_spend(self.base_url, self.key, self.http_get)

    def chat(self, model: str, messages: list[dict[str, Any]], max_tokens: int = 4000) -> str:
        """One completion, after the spend guard, with retries and backoff on API errors."""
        import openai

        check_model(model)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            guard(self.spend(), self.limit)
            try:
                r = self.client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens,
                                                        temperature=0.2)
            except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError,
                    openai.InternalServerError) as e:
                last = e
                if attempt < self.retries:
                    self.sleep(self.backoff * 2 ** attempt)
                continue
            except openai.APIStatusError as e:  # 4xx other than 429: retrying will not help
                raise ModelError(f"model call failed: HTTP {e.status_code}") from None
            u = r.usage
            self.usage.add(model, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)
            return r.choices[0].message.content or ""
        raise ModelError(f"model call failed after {self.retries + 1} tries: {type(last).__name__}")

    def chat_json(self, model: str, messages: list[dict[str, Any]], max_tokens: int = 4000) -> Any:
        """Like chat, but the reply must be JSON. Invalid JSON is retried, then raises ModelError."""
        msgs = list(messages)
        for attempt in range(self.json_retries + 1):
            text = self.chat(model, msgs, max_tokens)
            try:
                return parse_json(text)
            except json.JSONDecodeError as e:
                msgs = [*messages, {"role": "assistant", "content": text},
                        {"role": "user", "content": f"That was not valid JSON ({e.msg}). Reply with JSON only."}]
        raise ModelError(f"model {model} gave invalid JSON {self.json_retries + 1} times; stopping this worker")


def record_spend(run_dir: Path, name: str, client: ModelClient) -> float | None:
    """Write the key's spend to <run_dir>/spend.json under `name` (before/after). None if unreadable."""
    path = run_dir / "spend.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    try:
        spend: float | None = client.spend()
        data[name] = {"spend_usd": spend, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    except ModelError as e:
        spend = None
        data[name] = {"error": str(e)}
    if name == "after":
        data["usage"] = client.usage.to_dict()
        if data.get("before", {}).get("spend_usd") is not None and spend is not None:
            data["run_cost_usd"] = round(spend - data["before"]["spend_usd"], 6)
    path.write_text(json.dumps(data, indent=1))
    return spend
