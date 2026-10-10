"""Fake OpenAI and Anthropic provider. The scenario is the request's model name."""

from trueup.fake.server import SCENARIOS, FakeProvider, TruthLog

__all__ = ["SCENARIOS", "FakeProvider", "TruthLog"]
