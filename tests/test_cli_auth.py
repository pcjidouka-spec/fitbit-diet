from click.testing import CliRunner

from diet.cli import app


def test_auth_runs_oauth_flow(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["auth"])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs.get("port") == 8765


def test_auth_regen_cert_removes_existing_and_regenerates(
    tmp_path, monkeypatch, mocker
):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    # Pre-create dummy cert/key
    cert = tmp_path / "oauth_cert.pem"
    key = tmp_path / "oauth_key.pem"
    tmp_path.mkdir(parents=True, exist_ok=True)
    cert.write_text("OLD_CERT")
    key.write_text("OLD_KEY")
    gen_spy = mocker.patch("diet.oauth.generate_self_signed_cert", return_value=None)
    init_spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["auth", "--regen-cert"])
    assert result.exit_code == 0, result.output
    assert not cert.exists()  # removed before regen call
    assert not key.exists()
    gen_spy.assert_called_once()
    init_spy.assert_called_once()


def test_auth_custom_port(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["auth", "--port", "9999"])
    assert result.exit_code == 0, result.output
    _, kwargs = spy.call_args
    assert kwargs.get("port") == 9999
