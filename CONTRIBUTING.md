# Contributing

1. Install [uv](https://docs.astral.sh/uv/) and Python 3.12.
2. Run `uv sync`.
3. Make your change and add a test for it.
4. Run `uv run pytest -q` and make sure it passes.
5. Open a pull request that says what changed and why.

Rules:

- Code in `src/trueup/core/` must stay pure: no file, network, clock or environment access.
- Never print or log secret values. Report only whether a key is set.
- Write in plain words. Do not claim results that have not been shown.
