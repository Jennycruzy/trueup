from pathlib import Path
import json


def test_shop_agent_has_real_breaks_and_no_embedded_keys():
    text = Path("examples/shop_agent.py").read_text()
    assert '"anthropic-cut"' in text and '"agent-fail"' in text
    assert "TRUEUP_MODEL_KEY" in text and "sk-" not in text
    assert "FakeProvider" not in text


def test_witness_evidence_is_honest_about_failed_after_run():
    before = json.loads(Path("evidence/witness/before.json").read_text())
    after = json.loads(Path("evidence/witness/after.json").read_text())
    assert before["normal_calls"]["disagreements"] == 0
    assert after["targeted_before_marks"] == after["targeted_after_marks"] == 2
    assert after["new_fixer_attempt"]["model_calls"] == 1
    assert after["new_fixer_attempt"]["patch_created"] is False
