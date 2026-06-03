from datetime import datetime, timedelta

from diet import oauth
from diet.db import Token, open_db


def test_run_init_flow_binds_redirect_port(tmp_path, monkeypatch):
    """The loopback listener must bind the port advertised by GOOGLE_REDIRECT_URI,
    not the --port argument, so the two can't diverge."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "CID")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "CSEC")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:9100/callback")

    # Fix the generated state so the callback stub can echo it back.
    import secrets

    monkeypatch.setattr(secrets, "token_urlsafe", lambda n=16: "S")

    # No-op browser launch.
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: None)

    captured = {}

    def fake_callback_server(port: int = 8765, timeout_sec: int = 300):
        captured["port"] = port
        return oauth.CallbackResult(code="C", state="S")

    monkeypatch.setattr(oauth, "run_callback_server", fake_callback_server)

    async def fake_exchange(client_id, client_secret, code, redirect_uri):
        return Token(
            access_token="A1",
            refresh_token="R1",
            expires_at=datetime.now() + timedelta(seconds=3600),
            user_id="me",
        )

    monkeypatch.setattr(oauth, "exchange_code_for_token", fake_exchange)

    import diet.db as db

    monkeypatch.setattr(db, "save_token_atomic", lambda conn, tok: None)

    conn = open_db(tmp_path / "diet.db")
    # --port is 8765, but redirect advertises 9100; listener must bind 9100.
    oauth.run_init_flow(data_dir=tmp_path, port=8765, conn=conn)

    assert captured["port"] == 9100
