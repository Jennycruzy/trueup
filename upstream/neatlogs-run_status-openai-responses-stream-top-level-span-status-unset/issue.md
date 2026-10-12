<!-- Drafted by Trueup from recorded runs. Not posted. -->

# OpenAI Responses: a stream error event leaves the span status unset

## Symptom

Trueup ran each case against a fake provider, so it knows what really happened, and compared that with the exported spans:

- A Responses stream ends with an error event that the OpenAI SDK returns to the application.
- Expected: ERROR (app raised RuntimeError).
- Recorded: UNSET.

## Boundary

Affected cases: 1. Other checked cases on the same wrapper that remain correct: 20.

Checked on: latest release and main 202f8776ea.

## Repro

Standalone, 23 lines, needs only the library and the SDK; no API key, no network:

```python
"""neatlogs + OpenAI Responses: a terminal error event leaves the span UNSET.
Offline: a small event iterator stands in for the provider; export is off."""
from types import SimpleNamespace as NS

from neatlogs._wrap_utils import set_neatlogs_provider
from neatlogs.openai import wrap_openai_client
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

class Responses:
    def create(self, **kwargs):
        return iter([NS(type="response.created", response=None),
                     NS(type="error", message="server failed", code="server_error")])

exporter, provider = InMemorySpanExporter(), TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
set_neatlogs_provider(provider)
client = wrap_openai_client(NS(responses=Responses()))
list(client.responses.create(model="m", input="hi", stream=True))
span = exporter.get_finished_spans()[0]
errors = sum(event.name == "exception" for event in span.events)
print(f"span status: {span.status.status_code.name}; exception events: {errors}")
```

Output on the latest release:

```
span status: OK; exception events: 0
```

## Expected

A terminal Responses error event records ERROR status and an exception event.

## Before and after the proposed fix

| check | expected | latest release | proposed patch |
|---|---|---|---|
| top-level span status | ERROR (app raised RuntimeError) | UNSET | matches expected |

## Environment

Python 3.12.3, Linux x86_64. Versions: neatlogs 1.4.26, openai 3.29.0, anthropic 1.13.0, opentelemetry-sdk 1.45.1.

Searched issues and PRs first: `responses span status error stream` (0 hits, 2026-10-11); `span status error stream` (1 hits, 2026-10-11); `responses responses.stream` (0 hits, 2026-10-11); `responses Responses` (5 hits, 2026-10-11); `responses openai.py` (1 hits, 2026-10-11).