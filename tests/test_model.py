import json

from trueup.core import Finding, Mismatch, Observation, Run, Severity


def make_run() -> Run:
    obs = Observation(
        truth={"status": "error", "cost_usd": 0.01},
        trace={"status": "ok", "cost_usd": 0.02},
    )
    return Run(
        id="r1",
        scenario="crash-mid-stream",
        library="openinference",
        observation=obs,
        mismatches=(
            Mismatch("status", "error", "ok", Severity.HIGH),
            Mismatch("cost_usd", 0.01, 0.02, Severity.MEDIUM),
        ),
    )


def test_observation_round_trip():
    obs = Observation(truth={"a": 1}, trace={"a": 2})
    assert Observation.from_dict(obs.to_dict()) == obs


def test_mismatch_round_trip():
    m = Mismatch("refusal", True, False, Severity.LOW)
    assert Mismatch.from_dict(m.to_dict()) == m


def test_run_round_trip_through_json():
    run = make_run()
    assert Run.from_dict(json.loads(json.dumps(run.to_dict()))) == run


def test_finding_round_trip_through_json():
    f = Finding(
        id="f1",
        title="Stream crash recorded as ok",
        library="openinference",
        severity=Severity.HIGH,
        run_ids=("r1", "r2"),
        cause="exception swallowed in stream wrapper",
        details={"file": "wrapper.py"},
    )
    assert Finding.from_dict(json.loads(json.dumps(f.to_dict()))) == f


def test_finding_defaults_round_trip():
    f = Finding(id="f2", title="t", library="l", severity=Severity.LOW)
    assert Finding.from_dict(f.to_dict()) == f


def test_severity_ordering():
    assert Severity.LOW < Severity.MEDIUM < Severity.HIGH
    assert Severity.HIGH >= Severity.HIGH
    assert sorted([Severity.MEDIUM, Severity.HIGH, Severity.LOW]) == [
        Severity.LOW,
        Severity.MEDIUM,
        Severity.HIGH,
    ]
    assert max(Severity) is Severity.HIGH
