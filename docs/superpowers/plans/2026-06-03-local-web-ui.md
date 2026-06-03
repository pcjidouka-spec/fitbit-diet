# ローカル Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存 CLI `diet` の毎日フロー（sync → 運動/体重表示 → 食事入力 → 収支 → publish）を、自宅 PC のブラウザで完結できる `127.0.0.1` ローカル Web UI として提供する。

**Architecture:** FastAPI（loopback バインド限定）が薄い HTTP/セキュリティ層を担い、FastAPI 非依存の純 Python `service.py` が既存モジュール（`db` / `cli_helpers.run_sync_async` / `bmr` / `intake` / `formatters` / `helpers` / `publish`）を組み合わせて当日状態 DTO を作る。秘匿境界は `publish.build_records_from_db` を不変で再利用。フロントは素の HTML/JS + ローカル同梱 Chart.js。

**Tech Stack:** Python 3.11+ / FastAPI / uvicorn / 既存 sqlite + httpx スタック。テストは pytest + FastAPI `TestClient`。

**設計書:** `docs/superpowers/specs/2026-06-03-local-web-ui-design.md`

---

## File Structure

**新規作成:**
- `src/diet/web/__init__.py` — 空パッケージマーカー
- `src/diet/web/service.py` — FastAPI 非依存の純 Python。DTO 組み立て・既存モジュール呼び出し
- `src/diet/web/security.py` — 純粋な述語 + FastAPI ミドルウェア（loopback / Host / Origin / CSRF）
- `src/diet/web/app.py` — FastAPI アプリ定義・ルーティング・静的配信・index.html 動的配信
- `src/diet/web/static/app.js` — フロント JS（fetch + Chart.js 描画、note は textContent）
- `src/diet/web/static/chart.umd.min.js` — Chart.js ローカル同梱
- `src/diet/web/templates/index.html` — CSRF トークン埋め込みのため動的配信する HTML
- `tests/test_web_service.py` / `tests/test_web_api.py` / `tests/test_web_security.py` / `tests/test_web_boundary.py`

**修正:**
- `src/diet/intake.py` — click 非依存の純関数 `parse_kcal` を追加
- `src/diet/orchestrator.py:241-252` — `_parse_kcal` を `intake.parse_kcal` 呼び出しに置換
- `src/diet/cli.py` — `serve` コマンド追加
- `pyproject.toml` — `fastapi` / `uvicorn[standard]` を deps に追加

> パッケージング注（v1 スコープ外）: 本ツールは自宅 PC で `py -m uv run`（editable install, `Path(__file__).parent` で解決）から動かす前提なので `static/` `templates/` の非 Python 資産はそのまま読める。将来 wheel ビルドで配布する場合のみ `[tool.hatch.build.targets.wheel.force-include]` で資産を含める必要がある。

---

## Task 1: intake パースの純関数化（click 切り離し）

**Files:**
- Modify: `src/diet/intake.py`
- Modify: `src/diet/orchestrator.py:211-252`
- Test: `tests/test_intake.py`

- [ ] **Step 1: Write the failing test**

`tests/test_intake.py` に追記:

```python
import pytest
from diet.intake import parse_kcal, ParsedIntake


def test_parse_kcal_append():
    assert parse_kcal("+500") == ParsedIntake(kcal=500, op="append")


def test_parse_kcal_override_zero_allowed():
    assert parse_kcal("=0") == ParsedIntake(kcal=0, op="override")


def test_parse_kcal_empty_is_skip():
    assert parse_kcal("") is None
    assert parse_kcal("   ") is None


def test_parse_kcal_append_must_be_positive():
    with pytest.raises(ValueError):
        parse_kcal("+0")


def test_parse_kcal_negative_rejected():
    with pytest.raises(ValueError):
        parse_kcal("+-500")


def test_parse_kcal_garbage_rejected():
    with pytest.raises(ValueError):
        parse_kcal("abc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_intake.py -k parse_kcal -v`
Expected: FAIL (`ImportError: cannot import name 'parse_kcal'`)

- [ ] **Step 3: Write minimal implementation**

`src/diet/intake.py` に追記（`from dataclasses import dataclass` は既存）:

```python
@dataclass(frozen=True)
class ParsedIntake:
    kcal: int
    op: str  # 'append' | 'override'


def parse_kcal(raw: str) -> ParsedIntake | None:
    """Parse a freeform intake line into a ParsedIntake, or None for skip.

    click 非依存の純関数。CLI（orchestrator）と Web（service）で共用する。
    不正入力は ValueError を送出し、呼び出し側（click / FastAPI）が翻訳する。

      - ""            → None（skip）
      - "+N" (N>=1)   → ParsedIntake(N, "append")
      - "=N" (N>=0)   → ParsedIntake(N, "override")
    先頭 +/= を剥いてから int 化するため、"+-500" のような負値は弾く。
    """
    s = raw.strip()
    if not s:
        return None
    if s.startswith("+"):
        return ParsedIntake(kcal=_parse_int(s, s[1:], min_value=1), op="append")
    if s.startswith("="):
        return ParsedIntake(kcal=_parse_int(s, s[1:], min_value=0), op="override")
    raise ValueError(f"unrecognized input: {raw!r} (+追加 or =上書き or Enter)")


def _parse_int(raw: str, payload: str, *, min_value: int) -> int:
    try:
        kcal = int(payload)
    except ValueError as e:
        raise ValueError(
            f"unrecognized input: {raw!r} (+N or =N の N は非負整数)"
        ) from e
    if kcal < min_value:
        raise ValueError(
            f"unrecognized input: {raw!r} (N は {min_value} 以上である必要があります)"
        )
    return kcal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_intake.py -k parse_kcal -v`
Expected: PASS

- [ ] **Step 5: Rewire orchestrator to use the shared parser**

`src/diet/orchestrator.py` の `_handle_intake_input` を書き換え、`_parse_kcal` 内部関数を削除。`parse_kcal` の `ValueError` を `click.ClickException` に翻訳:

```python
def _handle_intake_input(conn, target: _date, raw: str) -> None:
    from diet.db import insert_intake_event
    from diet.intake import parse_kcal

    try:
        parsed = parse_kcal(raw)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if parsed is None:
        return
    now = datetime.now()
    insert_intake_event(conn, target, now, parsed.kcal, parsed.op)
```

（`_parse_kcal` 関数定義（旧 241-252 行）を削除する。）

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `py -m uv run pytest -q`
Expected: 全 PASS（既存テスト全件 + 新規 parse_kcal テスト）。
※ 「159」は MEMORY 由来の概数。Task 1 開始時に `py -m uv run pytest -q` で実カウントを確認し、以降の各タスクではその実数を基準に回帰を判定する（古い数字で本物の regression を見逃さないため）。

- [ ] **Step 7: Commit**

```bash
git add src/diet/intake.py src/diet/orchestrator.py tests/test_intake.py
git commit -m "refactor: extract click-free parse_kcal into intake.py for CLI/web reuse"
```

---

## Task 2: 依存追加 + web パッケージ骨組み

**Files:**
- Modify: `pyproject.toml`
- Create: `src/diet/web/__init__.py`

- [ ] **Step 1: Add FastAPI/uvicorn deps**

`pyproject.toml` の `dependencies` に追記:

```toml
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
```

- [ ] **Step 2: Sync deps**

Run: `py -m uv sync`
Expected: fastapi / uvicorn / starlette 等が解決・インストールされる

- [ ] **Step 3: Create empty web package + static dir**

`src/diet/web/__init__.py`（空ファイル）と `src/diet/web/static/.gitkeep`（空ファイル）を作成。
※ `static/.gitkeep` を先に作るのは、Task 6 で `StaticFiles(directory=.../static)` をマウントする際、ディレクトリが存在しないと `create_app` が `RuntimeError` になるため（Chart.js 本体は Task 10 で同梱）。

- [ ] **Step 4: Verify import works**

Run: `py -m uv run python -c "import diet.web; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/diet/web/__init__.py src/diet/web/static/.gitkeep
git commit -m "build: add fastapi+uvicorn deps and diet.web package skeleton"
```

---

## Task 3: service.py — 当日状態 DTO（純 Python）

**Files:**
- Create: `src/diet/web/service.py`
- Test: `tests/test_web_service.py`

`service.py` は **FastAPI に一切依存しない**。`conn`（sqlite）と `cfg` を受け取り、辞書 DTO を返す純関数群。

- [ ] **Step 1: Write the failing test**

`tests/test_web_service.py`:

```python
from datetime import date, datetime
from diet.db import open_db, save_config, Config, insert_intake_event, upsert_daily_activity, upsert_daily_weight, load_config
from diet.web.service import get_day_dto


def _seed(tmp_path):
    conn = open_db(tmp_path / "t.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path="C:/code/HPasaneel",
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    return conn


def test_get_day_dto_full(tmp_path):
    conn = _seed(tmp_path)
    d = date(2026, 6, 3)
    upsert_daily_activity(conn, d, steps=8000, distance_km=5.5,
                          total_calories_kcal=2500, active_energy_kcal=300)
    upsert_daily_weight(conn, d, 71.2)
    insert_intake_event(conn, d, datetime(2026, 6, 3, 12, 0), 600, "append", note="昼")
    dto = get_day_dto(conn, load_config(conn), d)

    assert dto["date"] == "2026-06-03"
    assert dto["steps"] == 8000
    assert dto["distance_km"] == 5.5
    assert dto["exercise_kcal"] == 300
    assert dto["weight"]["weight_kg"] == 71.2
    assert dto["weight"]["days_ago"] == 0
    assert dto["bmr"] > 0
    assert dto["intake"]["recorded_sum"] == 600
    # 収支は localhost に返す（秘匿対象だが物理境界は 127.0.0.1）
    assert "balance" in dto


def test_get_day_dto_no_data(tmp_path):
    conn = _seed(tmp_path)
    dto = get_day_dto(conn, load_config(conn), date(2026, 6, 3))
    assert dto["steps"] is None
    assert dto["weight"] is None
    assert dto["bmr"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_web_service.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Write minimal implementation**

`src/diet/web/service.py`:

```python
"""FastAPI 非依存の純 Python サービス層。

既存モジュール（db / bmr / intake / formatters / helpers）を組み合わせて
当日状態 DTO を組み立てる。HTTP の知識を持たない（例外は汎用 ValueError 等）。
"""
from datetime import date as _date, timedelta

from diet.bmr import age_at, mifflin_st_jeor
from diet.db import (
    Config,
    get_daily_activity,
    get_events_for_date,
    get_events_in_range,
    get_latest_weight_on_or_before,
)
from diet.formatters import format_balance, format_intake_display
from diet.helpers import resolve_exercise_kcal
from diet.intake import decide_intake_kcal, past_avg, recorded_sum


def get_day_dto(conn, cfg: Config, target: _date) -> dict:
    """当日状態 DTO。運動・体重・BMR・食事累積・収支を 1 つの辞書で返す。

    ★ このレスポンスは localhost ブラウザにのみ返る（食事 kcal/収支を含む）。
    publish には絶対に渡さない（publish 経路は build_records_from_db を使う）。
    """
    activity = get_daily_activity(conn, target)
    weight = get_latest_weight_on_or_before(conn, target)

    bmr = None
    weight_dto = None
    if weight is not None:
        days_ago = (target - weight.date).days
        weight_dto = {
            "weight_kg": weight.weight_kg,
            "measured_date": weight.date.isoformat(),
            "days_ago": days_ago,
        }
        age = age_at(cfg.birthday, target)
        bmr = mifflin_st_jeor(weight.weight_kg, cfg.height_cm, age, cfg.sex)

    history = get_events_in_range(conn, target - timedelta(days=14), target)
    avg, n = past_avg(history, target)
    today_events = get_events_for_date(conn, target)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    exercise = resolve_exercise_kcal(activity)

    balance = None
    if bmr is not None and weight is not None and activity is not None:
        balance = format_balance(
            decision.intake_kcal, bmr, exercise,
            activity.steps, activity.distance_km, weight.weight_kg,
        )

    return {
        "date": target.isoformat(),
        "steps": activity.steps if activity else None,
        "distance_km": activity.distance_km if activity else None,
        "exercise_kcal": exercise if activity else None,
        "weight": weight_dto,
        "bmr": int(bmr) if bmr is not None else None,
        "intake": {
            "recorded_sum": recorded_sum(today_events),
            "decision_kcal": decision.intake_kcal,
            "label": decision.label,
            "display": format_intake_display(decision),
        },
        "balance": balance,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_web_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diet/web/service.py tests/test_web_service.py
git commit -m "feat(web): pure-python get_day_dto service for current-day state"
```

---

## Task 4: service.py — history / intake / weight / sync / publish / auth

**Files:**
- Modify: `src/diet/web/service.py`
- Test: `tests/test_web_service.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_service.py` に追記:

```python
from diet.web.service import (
    get_history_dto, apply_intake, record_weight, auth_status, run_publish,
)


def test_apply_intake_appends(tmp_path):
    conn = _seed(tmp_path)
    d = date(2026, 6, 3)
    apply_intake(conn, d, "+500")
    apply_intake(conn, d, "+300")
    dto = get_day_dto(conn, load_config(conn), d)
    assert dto["intake"]["recorded_sum"] == 800


def test_apply_intake_invalid_raises_valueerror(tmp_path):
    conn = _seed(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        apply_intake(conn, date(2026, 6, 3), "abc")


def test_record_weight(tmp_path):
    conn = _seed(tmp_path)
    d = date(2026, 6, 3)
    record_weight(conn, d, 70.5)
    assert get_day_dto(conn, load_config(conn), d)["weight"]["weight_kg"] == 70.5


def test_record_weight_rejects_nonpositive(tmp_path):
    conn = _seed(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        record_weight(conn, date(2026, 6, 3), 0.0)


def test_history_dto_shape(tmp_path):
    conn = _seed(tmp_path)
    upsert_daily_weight(conn, date(2026, 6, 1), 72.0)
    rows = get_history_dto(conn, load_config(conn), date(2026, 6, 3), days=7)
    assert isinstance(rows, list)
    assert all("date" in r for r in rows)


def test_auth_status_no_token(tmp_path):
    conn = _seed(tmp_path)
    assert auth_status(conn)["authenticated"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_web_service.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Write minimal implementation**

`src/diet/web/service.py` に追記:

```python
import asyncio
from datetime import datetime

from diet.db import (
    insert_intake_event,
    load_token,
    upsert_daily_weight,
)
from diet.intake import parse_kcal


def apply_intake(conn, target: _date, raw: str) -> None:
    """食事入力を 1 件保存。不正入力は ValueError（呼び出し側が 400 に翻訳）。"""
    parsed = parse_kcal(raw)  # ValueError on bad input
    if parsed is None:
        return
    insert_intake_event(conn, target, datetime.now(), parsed.kcal, parsed.op)


def record_weight(conn, target: _date, kg: float) -> None:
    """体重手動入力。非正値は ValueError（呼び出し側が 400 に翻訳）。"""
    if kg <= 0:
        raise ValueError("weight must be positive")
    upsert_daily_weight(conn, target, kg)


def get_history_dto(conn, cfg: Config, target: _date, days: int) -> list[dict]:
    """過去 `days` 日のグラフ用履歴（運動・体重）。秘匿フィールドは含めない。"""
    rows = []
    for offset in range(days - 1, -1, -1):
        d = target - timedelta(days=offset)
        a = get_daily_activity(conn, d)
        w = get_latest_weight_on_or_before(conn, d)
        rows.append({
            "date": d.isoformat(),
            "steps": a.steps if a else None,
            "exercise_kcal": resolve_exercise_kcal(a) if a else None,
            "weight_kg": w.weight_kg if w else None,
        })
    return rows


def auth_status(conn) -> dict:
    """OAuth token の有無を返す（auth 自体は v1 では CLI 据え置き）。"""
    return {"authenticated": load_token(conn) is not None}


def run_sync(conn, days: int) -> None:
    """Google Health 同期。既存 run_sync_async の pass-through。

    ★ sync は未だライブ未検証（ASSUMED フィールドは client adapter に隔離）。
    例外はそのまま送出し、app 層が 502/503 + RefreshTokenError 等で翻訳する。
    """
    from diet.cli_helpers import run_sync_async
    asyncio.run(run_sync_async(conn, days=days))


def run_publish(conn, cfg: Config, target: _date) -> None:
    """HPasaneel publish。秘匿境界は build_records_from_db（5 フィールド allowlist）。"""
    from pathlib import Path
    from diet.publish import build_records_from_db, publish_to_hpasaneel

    if cfg.hpasaneel_path is None:
        raise ValueError("hpasaneel_path not configured")
    records = build_records_from_db(conn, [target])
    publish_to_hpasaneel(
        Path(cfg.hpasaneel_path), cfg.hpasaneel_diet_root, records, do_push=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_web_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diet/web/service.py tests/test_web_service.py
git commit -m "feat(web): service-layer intake/weight/history/sync/publish/auth helpers"
```

---

## Task 5: security.py — 純述語 + ミドルウェア

**Files:**
- Create: `src/diet/web/security.py`
- Test: `tests/test_web_security.py`

防御（spec §3.2 フルセット）: loopback クライアント / Host 検証 / mutation 時 Origin / CSRF トークン。純述語を切り出して単体テスト、ミドルウェア配線は Task 9 の TestClient で統合テストする。

- [ ] **Step 1: Write the failing test (pure predicates)**

`tests/test_web_security.py`:

```python
from diet.web.security import is_loopback_host, host_header_ok, origin_ok


def test_is_loopback_host():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("0.0.0.0")


def test_host_header_ok():
    assert host_header_ok("127.0.0.1:8770", 8770)
    assert host_header_ok("localhost:8770", 8770)
    assert not host_header_ok("evil.com:8770", 8770)
    assert not host_header_ok("127.0.0.1:9999", 8770)  # wrong port


def test_origin_ok():
    assert origin_ok("http://127.0.0.1:8770", 8770)
    assert origin_ok("http://localhost:8770", 8770)
    assert not origin_ok("http://evil.com", 8770)
    assert not origin_ok(None, 8770)  # missing Origin on mutation → reject
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_web_security.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Write pure predicates + middleware**

`src/diet/web/security.py`:

```python
"""localhost ブラウザセキュリティ（spec §3.2 フルセット）。

127.0.0.1 バインドだけでは DNS rebinding を防げないため、Host 検証・
mutation 時 Origin チェック・CSRF トークン・loopback クライアント確認を行う。
"""
import ipaddress

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_LOOPBACK_NAMES = {"localhost"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Starlette の TestClient は request.client.host を文字列 "testclient" にする。
# 実 IP ではないので is_loopback_host では弾かれてしまうため、client-IP 防御
# （belt-and-suspenders）の許可リストに含める。本番では uvicorn が 127.0.0.1
# バインドなので実クライアントは必ず loopback。主防御は Host/Origin/CSRF。
_ALLOWED_CLIENT_HOSTS = {"testclient"}


def is_loopback_host(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _hostname(value: str) -> tuple[str, int | None]:
    """'127.0.0.1:8770' → ('127.0.0.1', 8770)。ポート無しは (host, None)。"""
    if value.startswith("[") and "]" in value:  # IPv6 literal
        host, _, rest = value[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") else None
        return host, port
    host, sep, p = value.partition(":")
    return host, (int(p) if sep and p.isdigit() else None)


def host_header_ok(host_header: str | None, port: int) -> bool:
    if not host_header:
        return False
    host, hport = _hostname(host_header)
    return is_loopback_host(host) and hport == port


def origin_ok(origin: str | None, port: int) -> bool:
    if not origin:
        return False
    scheme, _, rest = origin.partition("://")
    if scheme not in ("http", "https"):
        return False
    host, hport = _hostname(rest)
    return is_loopback_host(host) and hport == port


class LocalhostSecurityMiddleware(BaseHTTPMiddleware):
    """Host / Origin / CSRF / loopback を強制する。"""

    def __init__(self, app, *, port: int, csrf_token: str):
        super().__init__(app)
        self.port = port
        self.csrf_token = csrf_token

    async def dispatch(self, request, call_next):
        if not host_header_ok(request.headers.get("host"), self.port):
            return JSONResponse({"code": "bad_host", "detail": "invalid Host header"}, status_code=400)
        client = request.client
        if (client is not None
                and client.host not in _ALLOWED_CLIENT_HOSTS
                and not is_loopback_host(client.host)):
            return JSONResponse({"code": "not_loopback", "detail": "loopback only"}, status_code=403)
        if request.method not in SAFE_METHODS:
            if not origin_ok(request.headers.get("origin"), self.port):
                return JSONResponse({"code": "bad_origin", "detail": "invalid Origin"}, status_code=403)
            if request.headers.get("x-csrf-token") != self.csrf_token:
                return JSONResponse({"code": "bad_csrf", "detail": "invalid CSRF token"}, status_code=403)
        return await call_next(request)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_web_security.py -v`
Expected: PASS（純述語）

- [ ] **Step 5: Commit**

```bash
git add src/diet/web/security.py tests/test_web_security.py
git commit -m "feat(web): localhost security predicates + middleware (Host/Origin/CSRF/loopback)"
```

---

## Task 6: app.py — FastAPI アプリ + GET エンドポイント + 静的配信

**Files:**
- Create: `src/diet/web/app.py`
- Create: `src/diet/web/templates/index.html`（最小プレースホルダ、Task 10 で本実装）
- Test: `tests/test_web_api.py`

`app.py` は `create_app(data_dir, port)` ファクトリで、毎リクエストに新しい `conn` を開く依存（sqlite はスレッド跨ぎ不可のため）。CSRF トークンはアプリ生成時に `secrets.token_urlsafe(32)` で 1 つ生成。

- [ ] **Step 1: Write the failing test**

`tests/test_web_api.py`:

```python
from datetime import date
from fastapi.testclient import TestClient
from diet.db import open_db, save_config, Config
from diet.web.app import create_app

PORT = 8770
HOST_HEADERS = {"host": f"127.0.0.1:{PORT}"}


def _seed_dir(tmp_path):
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path=str(tmp_path / "hp"),
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    conn.close()
    return tmp_path


def _client(tmp_path):
    app = create_app(data_dir=_seed_dir(tmp_path), port=PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_index_served_with_csrf(tmp_path):
    r = _client(tmp_path).get("/", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_api_day(tmp_path):
    r = _client(tmp_path).get("/api/day", headers=HOST_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "date" in body and "intake" in body


def test_api_history(tmp_path):
    r = _client(tmp_path).get("/api/history?days=7", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_auth_status(tmp_path):
    r = _client(tmp_path).get("/api/auth/status", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert r.json()["authenticated"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_web_api.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Write minimal implementation**

`src/diet/web/templates/index.html`（プレースホルダ）:

```html
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="csrf-token" content="{csrf_token}"><title>diet</title></head>
<body><div id="app">loading…</div><script src="/static/app.js"></script></body></html>
```

`src/diet/web/app.py`:

```python
"""FastAPI アプリ。loopback 限定のローカル Web UI（spec §2）。"""
import secrets
from datetime import date as _date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from diet.db import load_config, open_db
from diet.web import service
from diet.web.security import LocalhostSecurityMiddleware

_HERE = Path(__file__).parent
_TEMPLATE = (_HERE / "templates" / "index.html").read_text(encoding="utf-8")


def create_app(data_dir: Path, port: int) -> FastAPI:
    # ポート 80/443 等の特権ポートは拒否する。ブラウザはデフォルトポート
    # (80/443) のとき Host/Origin から `:port` を省略するため、security 述語
    # （省略ポートを拒否する）と整合せず正当なリクエストまで弾いてしまう。
    # 本ツールは loopback 開発用なので高位ポート固定でよい（codex P2 を源流封じ）。
    if port < 1024:
        raise ValueError(f"port must be >= 1024 (got {port}); 80/443 unsupported")
    csrf_token = secrets.token_urlsafe(32)
    app = FastAPI()
    app.add_middleware(LocalhostSecurityMiddleware, port=port, csrf_token=csrf_token)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")

    db_path = data_dir / "diet.db"

    def _conn():
        return open_db(db_path)

    def _today(cfg) -> _date:
        return datetime.now(ZoneInfo(cfg.timezone)).date()

    def _target(cfg, date_str: str | None) -> _date:
        return _date.fromisoformat(date_str) if date_str else _today(cfg)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(_TEMPLATE.replace("{csrf_token}", csrf_token))

    @app.get("/api/day")
    def api_day(date: str | None = Query(default=None)):
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        return service.get_day_dto(conn, cfg, _target(cfg, date))

    @app.get("/api/history")
    def api_history(days: int = Query(default=14, ge=1, le=90),
                    date: str | None = Query(default=None)):
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        return service.get_history_dto(conn, cfg, _target(cfg, date), days=days)

    @app.get("/api/auth/status")
    def api_auth_status():
        return service.auth_status(_conn())

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_web_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diet/web/app.py src/diet/web/templates/index.html tests/test_web_api.py
git commit -m "feat(web): FastAPI app factory + GET endpoints (day/history/auth) + static mount"
```

---

## Task 7: app.py — POST エンドポイント（sync/intake/weight/publish）+ エラー semantics

**Files:**
- Modify: `src/diet/web/app.py`
- Test: `tests/test_web_api.py`

エラーコード（spec §3.3）: sync 失敗 502/503、config 欠如 409、publish 衝突 409、その他 publish 500、入力 400。安定 `code` を JSON に併記。POST テストは Origin + CSRF ヘッダが必要。

- [ ] **Step 1: Write the failing tests**

`tests/test_web_api.py` に追記:

```python
def _post_headers(client_app_csrf):
    pass  # see helper below


def _client_with_csrf(tmp_path):
    """index から CSRF トークンを取り出し POST 用ヘッダを組む。"""
    app = create_app(data_dir=_seed_dir(tmp_path), port=PORT)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    html = client.get("/", headers=HOST_HEADERS).text
    import re
    token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    headers = {**HOST_HEADERS, "origin": f"http://127.0.0.1:{PORT}",
               "x-csrf-token": token}
    return client, headers


def test_post_intake_appends(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/intake", json={"raw": "+600"}, headers=h)
    assert r.status_code == 200
    day = client.get("/api/day", headers=HOST_HEADERS).json()
    assert day["intake"]["recorded_sum"] == 600


def test_post_intake_bad_input_400(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/intake", json={"raw": "abc"}, headers=h)
    assert r.status_code == 400
    assert r.json()["code"] == "bad_intake"


def test_post_weight_nonpositive_400(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/weight", json={"kg": 0}, headers=h)
    assert r.status_code == 400


def test_post_sync_failure_is_502(tmp_path, monkeypatch):
    client, h = _client_with_csrf(tmp_path)
    def boom(conn, days): raise RuntimeError("network down")
    monkeypatch.setattr("diet.web.service.run_sync", boom)
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code in (502, 503)
    assert r.json()["ok"] is False


def test_post_publish_conflict_409(tmp_path, monkeypatch):
    import subprocess
    client, h = _client_with_csrf(tmp_path)
    def boom(conn, cfg, target):
        raise subprocess.CalledProcessError(1, ["git", "push"])
    monkeypatch.setattr("diet.web.service.run_publish", boom)
    r = client.post("/api/publish", json={}, headers=h)
    assert r.status_code == 409
    assert "git pull --rebase" in r.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_web_api.py -k "post_" -v`
Expected: FAIL (404 — endpoints not defined)

- [ ] **Step 3: Write minimal implementation**

`src/diet/web/app.py` の `create_app` 内、`return app` の前に追記:

```python
    from pydantic import BaseModel

    class IntakeBody(BaseModel):
        raw: str
        date: str | None = None

    class WeightBody(BaseModel):
        kg: float
        date: str | None = None

    class SyncBody(BaseModel):
        days: int = 7

    class PublishBody(BaseModel):
        date: str | None = None

    @app.post("/api/intake")
    def api_intake(body: IntakeBody):
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        try:
            service.apply_intake(conn, _target(cfg, body.date), body.raw)
        except ValueError as e:
            return JSONResponse({"code": "bad_intake", "detail": str(e)}, status_code=400)
        return {"ok": True}

    @app.post("/api/weight")
    def api_weight(body: WeightBody):
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        try:
            service.record_weight(conn, _target(cfg, body.date), body.kg)
        except ValueError as e:
            return JSONResponse({"code": "bad_weight", "detail": str(e)}, status_code=400)
        return {"ok": True}

    @app.post("/api/sync")
    def api_sync(body: SyncBody):
        conn = _conn()
        try:
            service.run_sync(conn, days=body.days)
        except Exception as e:  # noqa: BLE001 — sync 失敗は non-fatal、UI に warning 表示
            return JSONResponse(
                {"ok": False, "code": "sync_failed", "warning": str(e)},
                status_code=502,
            )
        return {"ok": True}

    @app.post("/api/publish")
    def api_publish(body: PublishBody):
        import subprocess
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        target = _target(cfg, body.date)
        hint = (f"手動で `cd {cfg.hpasaneel_path} && "
                f"git pull --rebase && git push` してください")
        try:
            service.run_publish(conn, cfg, target)
        except subprocess.CalledProcessError as e:
            # git push 衝突等は回復可能 → 409
            return JSONResponse(
                {"code": "publish_conflict", "detail": f"{e}\n  {hint}"},
                status_code=409,
            )
        except ValueError as e:
            return JSONResponse({"code": "publish_unconfigured", "detail": str(e)}, status_code=409)
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {"code": "publish_failed", "detail": f"{e}\n  {hint}"},
                status_code=500,
            )
        return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_web_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diet/web/app.py tests/test_web_api.py
git commit -m "feat(web): POST endpoints (sync/intake/weight/publish) with stable error codes"
```

---

## Task 8: Web 層 publish 秘匿境界テスト

**Files:**
- Test: `tests/test_web_boundary.py`

`set_trace_callback` で `/api/publish` 実行時の SQL を捕捉し、`intake_events` / `config`（の note 系）/ `fitbit_token` に触れないことを assert。`run_publish` は `build_records_from_db` 経由なので CLI 境界と同一だが、Web 経路でも回帰防御を張る。

- [ ] **Step 1: Write the failing test**

`tests/test_web_boundary.py`:

```python
from datetime import date, datetime
from diet.db import (
    open_db, save_config, Config,
    insert_intake_event, upsert_daily_activity, upsert_daily_weight, load_config,
)
from diet.web import service


def test_web_publish_never_touches_intake_events(tmp_path, monkeypatch):
    """★ Web publish 経路が intake_events を SELECT しないことを実 SQL で検証。"""
    conn = open_db(tmp_path / "t.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path=str(tmp_path / "hp"),
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    d = date(2026, 6, 3)
    upsert_daily_activity(conn, d, steps=8000, distance_km=5.5,
                          total_calories_kcal=2500, active_energy_kcal=300)
    upsert_daily_weight(conn, d, 71.2)
    insert_intake_event(conn, d, datetime(2026, 6, 3, 12, 0), 600, "append",
                        note="秘匿ラーメン")

    # publish_to_hpasaneel の git/ファイル I/O は no-op に差し替え、SQL のみ観測。
    monkeypatch.setattr("diet.publish.publish_to_hpasaneel",
                        lambda *a, **k: None)

    captured = []
    conn.set_trace_callback(captured.append)
    service.run_publish(conn, load_config(conn), d)
    conn.set_trace_callback(None)

    forbidden = [s for s in captured
                 if any(t in s.lower() for t in ("intake_events", "fitbit_token"))]
    assert forbidden == [], f"web publish touched forbidden tables: {forbidden}"
```

- [ ] **Step 2: Run the test**

Run: `py -m uv run pytest tests/test_web_boundary.py -v`
Expected: PASS（`build_records_from_db` は元々 daily_activity/daily_weight のみ）

> 注: `service.run_publish` 内の `from diet.publish import publish_to_hpasaneel` がローカル import の場合、`monkeypatch.setattr("diet.publish.publish_to_hpasaneel", ...)` が効くよう、import を関数先頭で行う（Task 4 の実装どおり）。効かない場合は `monkeypatch.setattr("diet.web.service.publish_to_hpasaneel", ...)` ではなく module 属性をパッチする形に調整。

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_boundary.py
git commit -m "test(web): privacy boundary — publish path never selects intake_events"
```

---

## Task 9: セキュリティ統合テスト（ミドルウェア配線）

**Files:**
- Test: `tests/test_web_security.py`

純述語は Task 5 で済。ここでは TestClient でミドルウェア配線（Host 拒否 / Origin 拒否 / CSRF 欠如 / loopback）を検証。

- [ ] **Step 1: Write the failing tests**

`tests/test_web_security.py` に追記:

```python
from datetime import date
from fastapi.testclient import TestClient
from diet.db import open_db, save_config, Config
from diet.web.app import create_app

PORT = 8771


def _client(tmp_path):
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path=str(tmp_path / "hp"),
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    conn.close()
    app = create_app(data_dir=tmp_path, port=PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_bad_host_rejected(tmp_path):
    r = _client(tmp_path).get("/api/day", headers={"host": "evil.com"})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_host"


def test_mutation_without_origin_rejected(tmp_path):
    r = _client(tmp_path).post("/api/intake", json={"raw": "+1"},
                               headers={"host": f"127.0.0.1:{PORT}"})
    assert r.status_code == 403
    assert r.json()["code"] in ("bad_origin", "bad_csrf")


def test_mutation_bad_origin_rejected(tmp_path):
    r = _client(tmp_path).post("/api/intake", json={"raw": "+1"},
                               headers={"host": f"127.0.0.1:{PORT}",
                                        "origin": "http://evil.com"})
    assert r.status_code == 403
    assert r.json()["code"] == "bad_origin"


def test_mutation_missing_csrf_rejected(tmp_path):
    r = _client(tmp_path).post("/api/intake", json={"raw": "+1"},
                               headers={"host": f"127.0.0.1:{PORT}",
                                        "origin": f"http://127.0.0.1:{PORT}"})
    assert r.status_code == 403
    assert r.json()["code"] == "bad_csrf"
```

- [ ] **Step 2: Run test to verify it passes (middleware already built in Task 5/6)**

Run: `py -m uv run pytest tests/test_web_security.py -v`
Expected: PASS

> 注: TestClient の `request.client.host` は `"testclient"`。Task 5 のミドルウェアは
> これを `_ALLOWED_CLIENT_HOSTS` で許可済みなので、Host/Origin/CSRF の各防御だけが
> 発火する（client-IP 防御は本番 127.0.0.1 バインド時の belt-and-suspenders）。

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_security.py
git commit -m "test(web): middleware integration — Host/Origin/CSRF rejection"
```

---

## Task 10: フロントエンド（index.html 本実装 + app.js + Chart.js 同梱）

**Files:**
- Modify: `src/diet/web/templates/index.html`
- Create: `src/diet/web/static/app.js`
- Create: `src/diet/web/static/chart.umd.min.js`

- [ ] **Step 1: Vendor Chart.js locally**

Run（Chart.js UMD を static に取得。CDN 非依存にするためファイルを同梱）:

```bash
py -c "import urllib.request; urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js', 'src/diet/web/static/chart.umd.min.js')"
```

Verify: `ls -l src/diet/web/static/chart.umd.min.js`（数十 KB あること）

> オフライン等で取得できない場合のフォールバック: 別マシンや npm（`npm pack chart.js`）から `chart.umd.min.js` を入手して同パスに手動配置すればよい（同梱が目的なので入手経路は問わない）。

- [ ] **Step 2: Write index.html**

毎日フロー UI。`<meta name="csrf-token">` は app.py が `{csrf_token}` を置換。運動/体重表示、食事入力フォーム、収支表示、sync/publish ボタン、履歴チャート canvas。**note の描画は app.js 側で必ず `textContent`**。

```html
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{csrf_token}">
  <title>diet — 今日のフロー</title>
  <style>/* 最小限のスタイル。自宅 PC 用、装飾は控えめ */</style>
</head>
<body>
  <h1>今日のダイエット</h1>
  <button id="sync-btn">Google Health 同期</button>
  <section id="summary"></section>
  <form id="intake-form">
    <input id="intake-input" placeholder="+追加 / =上書き" autocomplete="off">
    <button type="submit">入力</button>
  </form>
  <section id="balance"></section>
  <button id="publish-btn">HPasaneel に公開（運動・体重のみ）</button>
  <canvas id="history-chart"></canvas>
  <div id="toast"></div>
  <script src="/static/chart.umd.min.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write app.js**

`src/diet/web/static/app.js`。要件:
- CSRF トークンを `<meta>` から読み、POST 時に `X-CSRF-Token` ヘッダ + `Origin` は同一オリジン自動付与。
- `GET /api/day` → summary 描画、`GET /api/history` → Chart.js 折れ線。
- 食事/体重/sync/publish POST → トースト表示。sync が `{ok:false}` ならトーストに warning。
- **note 等のユーザ文字列は `el.textContent = value`（`innerHTML` 禁止）。**

```javascript
const CSRF = document.querySelector('meta[name="csrf-token"]').content;

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": CSRF},
    body: JSON.stringify(body),
  });
  return {status: r.status, body: await r.json()};
}

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;            // ★ textContent（XSS 対策）
}

async function loadDay() {
  const r = await fetch("/api/day");
  const d = await r.json();
  const s = document.getElementById("summary");
  s.textContent = "";             // clear
  // 各値を textContent で組み立て（innerHTML を使わない）
  // 歩数 / 距離 / 運動kcal / 体重 / BMR / 食事表示 / 収支
  const bal = document.getElementById("balance");
  bal.textContent = d.balance || "";
}

// intake-form submit → POST /api/intake → loadDay()
// sync-btn → POST /api/sync → ok:false なら toast(warning)
// publish-btn → POST /api/publish → toast
// loadHistory() → GET /api/history → new Chart(...)
// 初期化: loadDay(); loadHistory();
```

> app.js / index.html / Chart.js 同梱は**自宅 PC で手動ブラウザ確認**（spec §3.4-6）。自動 E2E は v1 スコープ外。

- [ ] **Step 4: Commit**

```bash
git add src/diet/web/static/ src/diet/web/templates/index.html
git commit -m "feat(web): frontend (index.html + app.js + vendored Chart.js, textContent rendering)"
```

---

## Task 11: `diet serve` コマンド + host 固定バリデーション

**Files:**
- Modify: `src/diet/cli.py`
- Test: `tests/test_cli_serve.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_serve.py`:

```python
from unittest.mock import patch
from click.testing import CliRunner
from diet.cli import app


def test_serve_invokes_uvicorn_on_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    with patch("uvicorn.run") as mock_run, \
         patch("diet.web.app.create_app") as mock_create:
        result = CliRunner().invoke(app, ["serve", "--port", "8770"])
    assert result.exit_code == 0
    mock_create.assert_called_once()
    # uvicorn は loopback host で起動
    _, kwargs = mock_run.call_args
    assert kwargs.get("host") == "127.0.0.1"
    assert kwargs.get("port") == 8770
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m uv run pytest tests/test_cli_serve.py -v`
Expected: FAIL（`serve` コマンド未定義 → exit_code != 0）

- [ ] **Step 3: Write minimal implementation**

`src/diet/cli.py` に追記:

```python
@app.command()
@click.option("--port", default=8770, type=click.IntRange(min=1024, max=65535))
def serve(port: int) -> None:
    """ローカル Web UI を 127.0.0.1 で起動（自宅 PC 専用）。

    --port は >=1024 のみ（80/443 等の特権ポートは security 述語の省略ポート
    拒否と整合しないため非対応。create_app でも同条件を二重に検証する）。
    """
    import uvicorn

    from diet.web.app import create_app

    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    fastapi_app = create_app(data_dir=data_dir, port=port)
    # host は loopback 固定。外部公開を許さない（spec §3.2-6）。
    click.echo(f"diet web UI: http://127.0.0.1:{port}  (Ctrl+C で停止)")
    uvicorn.run(fastapi_app, host="127.0.0.1", port=port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -m uv run pytest tests/test_cli_serve.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `py -m uv run pytest -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add src/diet/cli.py tests/test_cli_serve.py
git commit -m "feat(cli): add `diet serve` to launch loopback web UI"
```

---

## Task 12: ドキュメント更新

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`（任意: Web UI への参照を 1 行追記）

- [ ] **Step 1: Update README**

`README.md` に `diet serve` の使い方セクションを追加: 起動方法（`py -m uv run diet serve`）、ブラウザで `http://127.0.0.1:8770`、毎日フロー（sync→入力→公開）、秘匿境界（食事は localhost のみ・publish には出ない）、auth は `diet auth`（CLI）据え置きの旨。

- [ ] **Step 2: Manual smoke test (自宅 PC)**

Run: `py -m uv run diet serve --port 8770`
ブラウザで `http://127.0.0.1:8770` を開き、当日表示・食事入力・履歴チャート・publish ボタンが動くことを目視確認（spec §3.4-6）。sync は「ライブ未検証」と理解した上で押下確認。

- [ ] **Step 3: Commit**

```bash
git add README.md docs/superpowers/specs/2026-05-25-fitbit-diet-design.md
git commit -m "docs: document `diet serve` local web UI usage"
```

---

## 完了条件

- 全 12 タスク commit 済み、`py -m uv run pytest -q` 全 PASS（既存テスト全件 + 新規 web/security/boundary/serve テスト）。
- `diet serve` で localhost UI が起動し、毎日フローがブラウザで完結。
- 秘匿境界テスト（Task 8）と localhost セキュリティテスト（Task 5/9）が green。
- README に使い方記載。
- sync は CLI と同一 pass-through（ライブ E2E は別トラック、UI 上で未検証と明示）。
