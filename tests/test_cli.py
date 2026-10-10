import pytest

from trueup.cli import EXIT_ERROR, EXIT_OK, NOT_BUILT, main

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


@pytest.mark.parametrize("command", NOT_BUILT)
def test_unbuilt_commands_exit_2(command, capsys):
    assert main([command]) == EXIT_ERROR
    assert "not built yet" in capsys.readouterr().err
