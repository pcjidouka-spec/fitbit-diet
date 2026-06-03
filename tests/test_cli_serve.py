from unittest.mock import patch
from click.testing import CliRunner
from diet.cli import app


def test_serve_invokes_uvicorn_on_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    with patch("uvicorn.run") as mock_run, \
         patch("diet.web.app.create_app") as mock_create:
        result = CliRunner().invoke(app, ["serve", "--port", "8770"])
    assert result.exit_code == 0, result.output
    mock_create.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs.get("host") == "127.0.0.1"
    assert kwargs.get("port") == 8770


def test_serve_rejects_privileged_port():
    """--port は IntRange(min=1024) で弾かれる（特権ポート非対応）。"""
    result = CliRunner().invoke(app, ["serve", "--port", "80"])
    assert result.exit_code != 0
