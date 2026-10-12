<!-- Drafted by Trueup from recorded runs. Not posted. -->

# OpenAI Chat Completions: refusal text is missing from the output span

## Symptom

Trueup ran each case against a fake provider, so it knows what really happened, and compared that with the exported spans:

- A non-streamed chat refusal has null content and text in the refusal field.
- Expected: I can't help with that..
- Recorded: None.

## Boundary

Affected cases: 1. Other checked cases on the same wrapper that remain correct: 20.

Checked on: latest release and main 202f8776ea.

## Repro

Standalone, 22 lines, needs only the library and the SDK; no API key, no network:

```python
"""neatlogs + OpenAI Chat Completions: refusal text is not recorded.
Offline: a small response object stands in for the provider; export is off."""
from types import SimpleNamespace as NS

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.openai import wrap_openai_client
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

class Completions:
    def create(self, **kwargs):
        message = NS(role="assistant", content=None, refusal="I can't help with that.", tool_calls=[])
        return NS(id="r1", model="m", choices=[NS(index=0, message=message, finish_reason="stop")], usage=None)

exporter, provider = InMemorySpanExporter(), TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
set_neatlogs_provider(provider)
client = wrap_openai_client(NS(chat=NS(completions=Completions())))
client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
span = exporter.get_finished_spans()[0]
print("recorded output:", span.attributes.get("neatlogs.llm.output_messages.0.content"))
```

Output on the latest release:

```
recorded output: None
```

## Expected

When content is null and refusal contains text, record the refusal as assistant output.

## Before and after the proposed fix

| check | expected | latest release | proposed patch |
|---|---|---|---|
| output text | I can't help with that. | None | matches expected |

## Environment

Python 3.12.3, Linux x86_64. Versions: neatlogs 1.4.26, openai 3.29.0, anthropic 1.13.0, opentelemetry-sdk 1.45.1.

Searched issues and PRs first: `openai refusal` (0 hits, 2026-10-11); `refusal` (0 hits, 2026-10-11).