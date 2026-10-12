# Witness live result

These are real provider calls. “After” means after all three existing proven neatlogs patches were applied together to a temporary copy. It does not mean merged upstream.

| Kind of break | neatlogs before | neatlogs after Trueup's proposed patches | Really |
|---|---|---|---|
| Anthropic stream cable cut | LLM span OK; no exception event | LLM span ERROR; still no exception event | Stream cut; app raised |
| OpenAI Agents server rejection | Agent workflow OK | Agent workflow OK | Run failed; app raised |

The DISAGREE light therefore remained on for both targeted runs: **2 before → 2 after**. This is a useful negative result, not a successful repair claim.

- [Anthropic after trace](https://app.neatlogs.com/traces/845e5c3c3e9fa2cca12b25e7e524be9a)
- [Agents after trace](https://app.neatlogs.com/traces/ae9a41d4476106029c272bfd507d4dab)

The one allowed new fixer attempt cost $0.30826290. Its verifier reported a passing candidate, but overlapping resume processes left an empty `patch.diff`. An empty patch cannot be applied or accepted, so the live result remains 2 → 2 and the artifact failure is recorded in `evidence/witness/after.json`.
