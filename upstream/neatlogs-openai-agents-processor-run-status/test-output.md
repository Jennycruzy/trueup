# Test output, 12 Oct 2026 (neatlogs 1.4.26 + this patch, openai-agents 0.23.1, Python 3.12)

Without the fix (`git checkout neatlogs/openai_agents.py`, new test file kept):

    FAILED tests/unit/test_trueup_openai_agents_run_status.py::test_workflow_is_error_when_model_call_fails
    FAILED tests/unit/test_trueup_openai_agents_run_status.py::test_workflow_is_error_when_max_turns_exceeded
    2 failed, 4 passed

With the fix:

    6 passed

Whole unit suite (`pytest tests/unit --ignore=tests/unit/test_google_finish_reason_value.py`):

    before: 7 failed, 532 passed, 4 skipped   (5 missing-dependency failures + the 2 new tests)
    after:  5 failed, 534 passed, 4 skipped   (the same 5 missing-dependency failures)
