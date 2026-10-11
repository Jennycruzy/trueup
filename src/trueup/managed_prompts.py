"""Neatlogs-managed system prompts with a deterministic offline fallback."""

from __future__ import annotations

from typing import Callable


def production(name: str, fallback: str, *, enabled: bool = True,
               fetch: Callable[..., object] | None = None) -> str:
    """Fetch label ``production`` when tracing is configured; otherwise use the reviewed local text."""
    if not enabled:
        return fallback
    try:
        if fetch is None:
            from neatlogs import fetch_prompt

            fetch = fetch_prompt
        prompt = fetch(name, label="production")
        content = getattr(prompt, "content", None)
        return content if isinstance(content, str) and content.strip() else fallback
    except Exception:  # noqa: BLE001 - prompt management must not make Trueup unavailable
        return fallback
