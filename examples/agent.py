"""A small agent for `trueup audit examples/agent.py --library <lib>`.

One chat call; if the model asks for tools, it answers them and asks again.
The client reads OPENAI_BASE_URL, so audit can point it at the fake.
"""

import json

import openai


def main():
    client = openai.OpenAI(max_retries=0)
    messages = [{"role": "user", "content": "What is the weather in Lagos?"}]
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}]
    for _ in range(2):
        r = client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools)
        msg = r.choices[0].message
        if not msg.tool_calls:
            return msg.content or msg.refusal
        messages.append(msg.model_dump(exclude_none=True))
        for t in msg.tool_calls:
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps({"temp_c": 31})})
    return None
