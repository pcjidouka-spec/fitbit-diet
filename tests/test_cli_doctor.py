"""Tests for `diet doctor` preflight (offline env + DB validation)."""

from datetime import date

from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, open_db, save_config


def _seed_config(db_path):
    conn = open_db(db_path)
    save_config(
        conn,
        Config(
            birthday=date(1979, 12, 1),
            height_cm=169,
            sex="male",
            timezone="Asia/Tokyo",
            hpasaneel_path=None,
            hpasaneel_diet_root="content/diet",
            exercise_calorie_source=None,
            bootstrap_daily_kcal=2000,
        ),
    )


def _set_good_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-real-secret-xyz")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8765/callback")


def test_doctor_all_green_when_env_and_config_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    _set_good_env(monkeypatch)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "GOOGLE_CLIENT_ID" in result.output
    # token absent is advisory, exit 0
    assert "diet auth" in result.output


def test_doctor_fails_when_client_id_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8765/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "GOOGLE_CLIENT_ID" in result.output


def test_doctor_fails_when_secret_is_placeholder(tmp_path, monkeypatch):
    """`.env.example` placeholder should be detected as not configured."""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "your-client-secret")  # placeholder
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8765/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "placeholder" in result.output.lower() or "GOOGLE_CLIENT_SECRET" in result.output


def test_doctor_fails_when_redirect_uri_is_https(tmp_path, monkeypatch):
    """HTTPS / non-loopback redirect breaks the OAuth flow (rev 10 = HTTP loopback)."""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.com/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "GOOGLE_REDIRECT_URI" in result.output


def test_doctor_accepts_127_0_0_1_redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8765/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output


def test_doctor_fails_when_redirect_uri_has_no_port(tmp_path, monkeypatch):
    """ポート欠落 → 実際はポート80にリダイレクトされ callback サーバに届かない。"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "GOOGLE_REDIRECT_URI" in result.output


def test_doctor_fails_when_redirect_uri_port_non_numeric(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:abc/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "GOOGLE_REDIRECT_URI" in result.output


def test_doctor_fails_when_redirect_port_is_zero(tmp_path, monkeypatch):
    """port 0 は run_init_flow で falsy 扱い → callback を受け取れない。"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:0/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "GOOGLE_REDIRECT_URI" in result.output


def test_doctor_fails_when_redirect_path_not_exactly_callback(tmp_path, monkeypatch):
    """callback サーバは厳密に /callback のみ処理。/foo/callback は 404 になる。"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123-abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-x")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8765/foo/callback")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "GOOGLE_REDIRECT_URI" in result.output


def test_doctor_fails_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _set_good_env(monkeypatch)
    # no config seeded
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "diet init" in result.output


def test_doctor_token_status_reflects_db(tmp_path, monkeypatch):
    """When a token row exists, doctor reports it as present (advisory)."""
    from datetime import datetime, timedelta

    from diet.db import save_token_atomic, Token

    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    _set_good_env(monkeypatch)
    conn = open_db(tmp_path / "diet.db")
    save_token_atomic(
        conn,
        Token(
            access_token="a",
            refresh_token="r",
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="me",
        ),
    )
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    # absence message should NOT appear when token present
    assert "diet auth" not in result.output or "OK" in result.output
