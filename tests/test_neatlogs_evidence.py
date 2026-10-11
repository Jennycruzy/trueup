import json

from trueup.neatlogs_evidence import pull


class FakeReader:
    def call(self, tool, **args):
        if tool == "list_detections":
            return {"detections": [{"display_name": "lead withdrawn"}]}
        if tool == "get_detection_trend":
            return {"total": 2, "name": args["detection_name"]}
        if tool == "get_project_analytics":
            return {"view": args["view"], "trace_count": 3}
        if tool == "triage_list":
            return {"status": args["status"], "fixes": []}
        raise AssertionError(tool)


def test_pull_writes_only_reviewable_read_evidence(tmp_path):
    target = pull(tmp_path, FakeReader(), out=lambda _: None)
    detections = json.loads((target / "detections.json").read_text())
    assert detections["trends"][0]["trend"]["total"] == 2
    analytics = json.loads((target / "analytics.json").read_text())
    assert set(analytics["views"]) == {"kpis", "cost", "errors", "time", "detections", "workflows"}
    fixes = json.loads((target / "fix-suggestions.json").read_text())
    assert set(fixes["by_status"]) == {"draft", "open", "in_progress", "resolved", "archived"}
