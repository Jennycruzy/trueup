from pathlib import Path
import json


def test_shop_agent_has_real_breaks_and_no_embedded_keys():
    text = Path("examples/shop_agent.py").read_text()
    assert '"anthropic-cut"' in text and '"agent-fail"' in text
    assert "TRUEUP_MODEL_KEY" in text and "sk-" not in text
    assert "FakeProvider" not in text


def test_witness_evidence_shows_light_out_and_keeps_the_failed_first_try():
    before = json.loads(Path("evidence/witness/before.json").read_text())
    after = json.loads(Path("evidence/witness/after.json").read_text())
    assert before["normal_calls"]["disagreements"] == 0
    assert before["normal_calls"]["after_patches"]["disagreements"] == 0
    assert all(b["witness"] for b in before["breaks"])  # Witness itself saw each lie before
    assert after["targeted_before_marks"] == 2 and after["targeted_after_marks"] == 0
    earlier = after["earlier_attempt"]
    assert earlier["targeted_before_marks"] == earlier["targeted_after_marks"] == 2
    assert earlier["new_fixer_attempt"]["patch_created"] is False


def test_shop_agent_prints_witness_verdict_not_a_hard_coded_one():
    text = Path("examples/shop_agent.py").read_text()
    assert "witness.disagreements" in text
    assert 'record, light = "OK", "ON"' not in text
