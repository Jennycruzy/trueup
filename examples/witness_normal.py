"""Twenty normal real calls under neatlogs + Witness. Every one should leave the DISAGREE light off.

Mix: 7 plain, 6 streamed, 6 with a tool, 1 async (OpenAI-compatible endpoint from TRUEUP_MODEL_BASE_URL).
Prints one JSON line with the counts; credentials stay in the environment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid

import trueup.witness

TOOL = [{"type": "function", "function": {"name": "lookup_order", "description": "Look up an order",
                                          "parameters": {"type": "object", "properties": {"order": {"type": "string"}},
                                                         "required": ["order"]}}}]
ASK = [{"role": "user", "content": "Reply in five words: is refund lookup ready?"}]
ASK_TOOL = [{"role": "user", "content": "Look up order 1042 with the tool."}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument("--json-out")
    args = parser.parse_args()
    trueup.witness.watch()
    import neatlogs
    from openai import AsyncOpenAI, OpenAI
    session = args.session or "witness-normal-" + uuid.uuid4().hex[:10]
    neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], workflow_name="trueup-witness-normal",
                  instrumentations=["openai"], pii_enabled=False, user_id="jenny-builds", tags=["witness", "normal"])
    key, base = os.environ["TRUEUP_MODEL_KEY"], os.environ["TRUEUP_MODEL_BASE_URL"]
    client, aclient = OpenAI(api_key=key, base_url=base, max_retries=0), AsyncOpenAI(api_key=key, base_url=base, max_retries=0)
    mix = ["plain_sync"] * 7 + ["stream_sync"] * 6 + ["tool_sync"] * 6 + ["plain_async"]
    counts = {k: 0 for k in ("plain_sync", "stream_sync", "tool_sync", "plain_async")}
    disagreements, notes, errors = [], [], []
    try:
        for i, kind in enumerate(mix):
            with neatlogs.trace(name=f"normal-{i:02d}-{kind}", kind="AGENT", session_id=session):
                try:
                    with trueup.witness.run(f"normal-{i}") as run:
                        if kind == "plain_sync":
                            client.chat.completions.create(model="claude-haiku", messages=ASK, max_tokens=16)
                        elif kind == "stream_sync":
                            for _ in client.chat.completions.create(model="claude-haiku", messages=ASK, max_tokens=16,
                                                                     stream=True):
                                pass
                        elif kind == "tool_sync":
                            client.chat.completions.create(model="claude-haiku", messages=ASK_TOOL, tools=TOOL,
                                                           max_tokens=40)
                        else:
                            asyncio.run(aclient.chat.completions.create(model="claude-haiku", messages=ASK,
                                                                        max_tokens=16))
                except Exception as error:  # a real failure is reported, never hidden
                    errors.append(f"{kind}: {type(error).__name__}")
            counts[kind] += 1
            disagreements += [dict(d, call=kind) for d in run.disagreements]
            notes += [dict(n, call=kind) for n in run.notes]
    finally:
        neatlogs.flush(); neatlogs.shutdown()
    result = {"session_id": session, "total": sum(counts.values()), **counts,
              "disagreements": len(disagreements), "disagreement_details": disagreements,
              "notes": len(notes), "app_errors": errors}
    print(json.dumps(result))
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(result, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
