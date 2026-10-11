"""Repro: neatlogs on scenario oa-resp-tool. Returns one function call.
Offline: a local fake provider answers; no API keys, no network.
Run with neatlogs installed: PYTHONPATH=<trueup>/src python neatlogs-oa-resp-tool.py
"""
import gc, json, os
from trueup.runner.setups import CHILD_ENV, SETUPS, quiet_agents_sdk
os.environ.update(CHILD_ENV)  # content capture on, export off, fake keys
from trueup.core.compare import compare, leads
from trueup.core.model import Observation
from trueup.fake import FakeProvider
from trueup.runner import framework_apps, truth
from trueup.runner.apps import APPS
from trueup.runner.child import span_to_dict
from trueup.scenarios import get

s = get("oa-resp-tool")
exporter, flush = SETUPS["neatlogs"](s.framework)  # the library's recommended setup
if s.framework == "openai-agents":
    quiet_agents_sdk()  # drop the Agents SDK's own upload to api.openai.com
with FakeProvider() as fake:
    try:
        app = {"outcome": "ok", "result": APPS[s.app](fake.base_url, s.model)}
    except Exception as e:
        app = {"outcome": "exception", "exception_type": type(e).__name__, "message": str(e)}
    gc.collect()
    flush()
    log = fake.log.entries()
t = {**truth.derive(log, app, framework_apps.TOOL_RUNS), "expected": s.expected, "app": app, "fake_log": log}
spans = [span_to_dict(x) for x in exporter.get_finished_spans()]
for m in leads(compare(Observation(t, {"library": "neatlogs", "spans": spans}))):
    print(json.dumps(m.to_dict(), default=str))
