"""Install the span-level part of Trueup's Neatlogs detection pack."""

from __future__ import annotations

from typing import Any

from trueup.neatlogs_read import Reader

GROUP = "Trace truth (by Trueup)"
PACK = (
    {"display_name": "neatlogs: LLM succeeded without output", "type": "conditional",
     "description": "Flags successful Neatlogs/OpenInference/OpenLLMetry LLM spans with no output; https://github.com/neatlogs/neatlogs/pull/180.",
     "config": {"root": {"type": "group", "logic": "AND", "children": [
         {"type": "rule", "field": "status", "operator": "=", "value": "OK"},
         {"type": "rule", "field": "output", "operator": "is_empty"}]}},
     "run_on": {"frequency": "span_type", "span_types": ["LLM"]}},
    {"display_name": "neatlogs: LLM output was not recorded", "type": "conditional",
     "description": "Flags Neatlogs/OpenInference/OpenLLMetry LLM spans whose output is empty; https://github.com/neatlogs/neatlogs/pull/180.",
     "config": {"root": {"type": "group", "logic": "AND", "children": [
         {"type": "rule", "field": "output", "operator": "is_empty"}]}},
     "run_on": {"frequency": "span_type", "span_types": ["LLM"]}},
    {"display_name": "neatlogs: LLM token count was not recorded", "type": "conditional",
     "description": "Flags Neatlogs/OpenInference/OpenLLMetry LLM spans with zero total tokens; https://github.com/neatlogs/neatlogs/pull/180.",
     "config": {"root": {"type": "group", "logic": "AND", "children": [
         {"type": "rule", "field": "total_tokens", "operator": "=", "value": 0}]}},
     "run_on": {"frequency": "span_type", "span_types": ["LLM"]}},
)


class Writer(Reader):
    """Small write client kept separate from the read-only Reader.call allowlist."""

    def write(self, tool: str, **args: Any) -> Any:
        if tool not in {"create_detection_group", "create_detection"}:
            raise ValueError(f"write tool not allowed: {tool}")
        result = self._post("tools/call", {"name": tool, "arguments": args})
        if result.get("isError"):
            raise RuntimeError(f"{tool} failed")
        if result.get("structuredContent"):
            return result["structuredContent"]
        content = result.get("content") or []
        if len(content) == 1 and isinstance(content[0], dict):
            import json

            try:
                return json.loads(content[0].get("text", "{}"))
            except json.JSONDecodeError:
                pass
        return content


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("groups", "detections", "results"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def list_pack(reader: Reader) -> list[dict[str, Any]]:
    return [x for x in _items(reader.call("list_detections")) if x.get("display_name") in {
        p["display_name"] for p in PACK}]


def install(writer: Writer) -> dict[str, Any]:
    groups = _items(writer.call("list_detection_groups"))
    group = next((x for x in groups if x.get("name") == GROUP), None)
    if group is None:
        group = writer.write("create_detection_group", name=GROUP)
    group_id = group.get("id") or group.get("group_id")
    existing = {x.get("display_name") for x in _items(writer.call("list_detections", group_id=group_id))}
    created, skipped = [], []
    for detection in PACK:
        name = detection["display_name"]
        if name in existing:
            skipped.append(name)
            continue
        try:
            preview = writer.call("preview_detection", type=detection["type"], config=detection["config"],
                                  run_on=detection["run_on"], timeframe_days=14, limit=10)
        except Exception as error:  # one unsupported rule must not hide the rest of the pack
            skipped.append(f"{name} (preview failed: {type(error).__name__})")
            continue
        total = preview.get("total_count", 0) if isinstance(preview, dict) else 0
        if total <= 0:
            skipped.append(f"{name} (preview found 0)")
            continue
        writer.write("create_detection", group_id=group_id, **detection)
        created.append(name)
    return {"group": GROUP, "created": created, "skipped": skipped}
