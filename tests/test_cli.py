import json

from trueup.cli import EXIT_ERROR, EXIT_OK, main

SECRET_A = "nl-secret-value-123"
SECRET_B = "model-secret-value-456"


def test_doctor_with_keys_set_never_prints_values(monkeypatch, capsys):
    monkeypatch.setenv("NEATLOGS_API_KEY", SECRET_A)
    monkeypatch.setenv("TRUEUP_MODEL_KEY", SECRET_B)
    assert main(["doctor"]) == EXIT_OK
    out, err = capsys.readouterr()
    assert "NEATLOGS_API_KEY: set" in out
    assert "TRUEUP_MODEL_KEY: set" in out
    assert "python: 3." in out
    for secret in (SECRET_A, SECRET_B):
        assert secret not in out
        assert secret not in err


def test_doctor_with_keys_missing(monkeypatch, capsys):
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    monkeypatch.delenv("TRUEUP_MODEL_KEY", raising=False)
    assert main(["doctor"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "NEATLOGS_API_KEY: not set" in out
    assert "TRUEUP_MODEL_KEY: not set" in out


def test_sweep_case_unknown_id_exits_2(capsys):
    from trueup.cli import EXIT_ERROR

    assert main(["sweep", "openllmetry", "--case", "no-such-case"]) == EXIT_ERROR
    assert "unknown scenario" in capsys.readouterr().err


def test_sweep_case_runs_only_that_scenario(tmp_path):
    from trueup.sweep import sweep

    ran = []

    def fake_run(py, library, sid):
        ran.append(sid)
        return {"scenario": sid, "library": library, "status": "not_run", "reason": "test", "seconds": 0}

    sweep(tmp_path, "openllmetry", cases=["ag-run"], ensure=lambda r, l: tmp_path, run=fake_run,
          out=lambda _: None)
    assert ran == ["ag-run"]


def test_action_and_entire_plugin_entry():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    action = (root / "action.yml").read_text()
    assert "trueup audit" in action and "using: composite" in action
    assert 'entire-trueup = "trueup.cli:main"' in (root / "pyproject.toml").read_text()


def test_traced_worker_command_opens_named_worker(monkeypatch):
    from trueup import tracing
    from trueup.cli import traced_worker_command

    seen = {}

    def fake_run(run_id, target, command, body):
        seen.update(run_id=run_id, target=target, command=command)
        return body()

    class Span:
        def set_attribute(self, key, value):
            seen[key] = value

    from contextlib import contextmanager

    @contextmanager
    def fake_worker(name, **attrs):
        seen.update(worker=name, attrs=attrs)
        yield Span()

    monkeypatch.setattr(tracing, "run_traced", fake_run)
    monkeypatch.setattr(tracing, "worker", fake_worker)
    assert traced_worker_command("verify", "evidence", "trueup-reporter", lambda: EXIT_OK,
                                 run_id="r-verify") == EXIT_OK
    assert seen["run_id"] == "r-verify" and seen["target"] == "evidence"
    assert seen["command"] == "verify" and seen["worker"] == "trueup-reporter"
    assert seen["trueup.verdict"] == "ok"


def test_record_audit_requires_provider(capsys):
    assert main(["audit", "agent.py", "--library", "neatlogs", "--record"]) == EXIT_ERROR
    assert "--record requires --provider" in capsys.readouterr().err


def test_record_options_are_rejected_without_opt_in(capsys):
    assert main(["audit", "agent.py", "--library", "neatlogs", "--provider", "openai"]) == EXIT_ERROR
    assert "require --record" in capsys.readouterr().err


def test_every_command_accepts_json():
    from trueup.cli import build_parser

    parser = build_parser()
    for name, subparser in parser._subparsers._group_actions[0].choices.items():
        assert any(action.dest == "json" for action in subparser._actions), name


def test_json_output_is_one_stable_envelope(monkeypatch, capsys):
    monkeypatch.setattr("trueup.cli.reach_neatlogs", lambda *_: "test")
    monkeypatch.setattr("trueup.cli.reach_model", lambda *_: "test")
    assert main(["doctor", "--json"]) == EXIT_OK
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["command"] == "doctor" and payload["exit_code"] == 0 and payload["status"] == "ok"
    assert any(line.startswith("python:") for line in payload["stdout"])
    assert payload["stderr"] == [] and output.err == ""


def test_sweep_rejects_unknown_provider(capsys):
    assert main(["sweep", "neatlogs", "--provider", "gemini"]) == EXIT_ERROR
    assert "invalid --provider: gemini" in capsys.readouterr().err
