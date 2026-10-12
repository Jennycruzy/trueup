from pathlib import Path


def test_shop_agent_has_real_breaks_and_no_embedded_keys():
    text = Path("examples/shop_agent.py").read_text()
    assert '"anthropic-cut"' in text and '"agent-fail"' in text
    assert "TRUEUP_MODEL_KEY" in text and "sk-" not in text
    assert "FakeProvider" not in text
