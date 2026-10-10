"""Run one proposed scenario's app against the fake with no tracing library; print its truth as JSON.

python -m trueup.scenarios.untraced '<proposal json>'
"""

from __future__ import annotations

import json
import logging
import sys

from trueup.fake import FakeProvider
from trueup.runner import framework_apps, truth
from trueup.runner.apps import APPS
from trueup.runner.setups import quiet_agents_sdk


def main(argv: list[str]) -> int:
    p = json.loads(argv[0])
    logging.disable(logging.CRITICAL)
    if p["framework"] == "openai-agents":
        quiet_agents_sdk()
    framework_apps.TOOL_RUNS.clear()
    with FakeProvider() as f:
        try:
            app = {"outcome": "ok", "result": APPS[p["app"]](f.base_url, p["model"])}
        except Exception as e:  # noqa: BLE001 - the outcome is the data
            app = {"outcome": "exception", "exception_type": type(e).__name__}
        t = truth.derive(f.log.entries(), app, framework_apps.TOOL_RUNS)
    t.pop("response_ids", None)
    print(json.dumps(t, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
