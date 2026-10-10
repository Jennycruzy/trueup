"""Fake OpenAI and Anthropic provider. The scenario is the request's model name."""

from trueup.fake.server import AGENT_SCENARIOS, SCENARIOS, FakeProvider, TruthLog

__all__ = ["AGENT_SCENARIOS", "SCENARIOS", "FakeProvider", "TruthLog"]
