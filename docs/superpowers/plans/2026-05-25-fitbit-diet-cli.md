# Fitbit 連動ダイエット CLI 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fitbit API・Renpho 体重・手動食事入力を統合し、収支算出と HPasaneel ダッシュ公開を 1 つの対話型 CLI コマンド `diet` で完結させる。

**Architecture:** Python + uv 単一 CLI、SQLite ストレージ、Fitbit OAuth 2.0 (HTTPS localhost callback + 自己署名証明書)、純粋関数ファースト設計で TDD 高被覆。公開境界は 2 層 allowlist（DTO + JSON schema）で `note` 漏洩を構造的に防止。HPasaneel 側は Next.js + recharts のダッシュ 1 ページ追加。

**Tech Stack:** Python 3.11+, uv, httpx, click, jsonschema, cryptography, pytest, pytest-httpx; HPasaneel: Next.js 15 + recharts。

**Source spec:** `docs/superpowers/specs/2026-05-25-fitbit-diet-design.md` (rev 9)。実装中の不明点はすべて spec を一次ソースとして参照すること。

**Reference skills:**
- @superpowers:test-driven-development — 全タスクが Red → Green → Refactor の TDD で進行
- @superpowers:systematic-debugging — テストが想定外に通った／落ちた時はこちらへ

---

## File Structure

### Python パッケージ (`C:/code/fitbit連動ダイエット/`)

```
pyproject.toml                    # uv 管理、依存定義、entry point: diet = "diet.cli:app"
.env.example                      # FITBIT_CLIENT_ID/SECRET/REDIRECT_URI 雛形
.gitignore                        # data/, .env, oauth_*.pem, __pycache__, .venv
README.md                         # セットアップ手順、Fitbit dev portal 登録、Renpho 同期、初回 diet init

src/diet/
  __init__.py                     # __version__ のみ
  __main__.py                     # python -m diet エントリ (cli.app() 呼び出し)
  cli.py                          # click/typer 定義、diet/init/sync/calibrate/weight/baseline/show/auth
  orchestrator.py                 # diet コマンド本体の 5 ステップ対話フロー
  bmr.py                          # 純粋関数: age_at(birthday, target_date), mifflin_st_jeor(...)
  intake.py                       # 純粋関数: recorded_sum, is_complete_day, past_avg, decide_intake_kcal
  db.py                           # SQLite 接続・スキーマ・migration、各テーブル CRUD
  oauth.py                        # 自己署名証明書生成、HTTPS callback サーバー、token 交換、atomic rotation
  fitbit_client.py                # httpx ラッパー、token 自動 refresh、rate limit 追跡、各 endpoint
  publish.py                      # PublicDayRecord DTO、JSON schema、merge、git 操作
  calibrate.py                    # diet calibrate コマンド本体（カロリー候補比較表示）
  formatters.py                   # 各 intake label に対応する CLI 表示文字列生成
  config.py                       # config dataclass、DB との往復

tests/
  conftest.py                     # 共通 fixtures (tmp_db, sample_events, mock_fitbit)
  test_bmr.py
  test_intake.py
  test_intake_regression.py       # =0 断食日が水増しされない回帰テスト
  test_db.py
  test_oauth.py
  test_fitbit_client.py
  test_publish_boundary.py        # note "ラーメン特盛" 等が log.json に出ない検査
  test_publish_schema.py
  test_publish_merge.py
  test_orchestrator_e2e.py
  test_formatters.py
```

### HPasaneel 側 (`C:/code/HPasaneel/`)

```
app/diet/page.tsx                 # 新規: log.json import → recharts でグラフ描画
app/layout.tsx                    # 既存編集: メインナビに "Diet" 追加
content/diet/log.json             # diet コマンドが書き出す（gitignore しない、公開対象）
package.json                      # recharts 依存追加
```

---

## Phase 0: Scaffold

### Task 0.1: プロジェクト scaffold + uv 初期化

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Modify: `.gitignore` (data/, .env, oauth_*.pem 追加)
- Create: `src/diet/__init__.py`
- Create: `src/diet/__main__.py`
- Create: `src/diet/cli.py` (空の app 定義のみ)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py` (空)

- [ ] **Step 1: pyproject.toml を作成**

```toml
[project]
name = "fitbit-diet"
version = "0.1.0"
description = "Personal diet tracking CLI integrating Fitbit, Renpho, and HPasaneel publish"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "click>=8.1",
  "python-dotenv>=1.0",
  "jsonschema>=4.21",
  "cryptography>=42.0",
]

[project.scripts]
diet = "diet.cli:app"

[dependency-groups]
dev = [
  "pytest>=8.0",
  "pytest-httpx>=0.30",
  "freezegun>=1.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/diet"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: .env.example を作成**

```
FITBIT_CLIENT_ID=
FITBIT_CLIENT_SECRET=
FITBIT_REDIRECT_URI=https://localhost:8765/callback
```

- [ ] **Step 3: .gitignore を更新（既存末尾に追記）**

既存 `.gitignore` を Read で確認後、以下を追加:

```
# project-specific
data/
.env
*.pem
oauth_cert.pem
oauth_key.pem
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: 空のソース構造を作成**

`src/diet/__init__.py`:
```python
__version__ = "0.1.0"
```

`src/diet/__main__.py`:
```python
from diet.cli import app

if __name__ == "__main__":
    app()
```

`src/diet/cli.py`:
```python
import click

@click.group()
def app() -> None:
    """Personal diet tracking CLI."""
```

`tests/__init__.py`: 空。

`tests/conftest.py`: 空。

- [ ] **Step 5: 依存解決と smoke**

```bash
uv sync
uv run python -c "import diet; print(diet.__version__)"
uv run diet --help
```
Expected: `0.1.0` と click の help がそれぞれ表示される。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example .gitignore src/ tests/
git commit -m "feat: project scaffold (uv + click + pytest)"
```

---

## Phase 1: 純粋関数（bmr.py, intake.py）

### Task 1.1: bmr.py — age_at 関数

**Files:**
- Create: `src/diet/bmr.py`
- Test: `tests/test_bmr.py`

- [ ] **Step 1: テストを書く**

`tests/test_bmr.py`:
```python
from datetime import date
from diet.bmr import age_at

BIRTHDAY = date(1979, 12, 1)

def test_age_at_day_before_birthday():
    assert age_at(BIRTHDAY, date(2026, 11, 30)) == 46

def test_age_at_birthday():
    assert age_at(BIRTHDAY, date(2026, 12, 1)) == 47

def test_age_at_day_after_birthday():
    assert age_at(BIRTHDAY, date(2026, 12, 2)) == 47

def test_age_at_birth_date():
    assert age_at(BIRTHDAY, date(1979, 12, 1)) == 0

def test_age_at_future_year_pre_birthday():
    assert age_at(BIRTHDAY, date(2030, 11, 30)) == 50

def test_age_at_future_year_post_birthday():
    assert age_at(BIRTHDAY, date(2030, 12, 1)) == 51
```

- [ ] **Step 2: 失敗確認**

```bash
uv run pytest tests/test_bmr.py -v
```
Expected: ImportError or ModuleNotFoundError on `from diet.bmr import age_at`。

- [ ] **Step 3: 実装**

`src/diet/bmr.py`:
```python
from datetime import date

def age_at(birthday: date, target_date: date) -> int:
    """Return age in years on target_date given birthday.

    Both arguments must be date objects already in the target timezone.
    Caller is responsible for timezone normalization.
    """
    age = target_date.year - birthday.year
    if (target_date.month, target_date.day) < (birthday.month, birthday.day):
        age -= 1
    return age
```

- [ ] **Step 4: テストパス確認**

```bash
uv run pytest tests/test_bmr.py -v
```
Expected: 6 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/bmr.py tests/test_bmr.py
git commit -m "feat(bmr): age_at handles birthday boundary correctly"
```

---

### Task 1.2: bmr.py — Mifflin-St Jeor 式

**Files:**
- Modify: `src/diet/bmr.py`
- Modify: `tests/test_bmr.py`

- [ ] **Step 1: テストを追記**

`tests/test_bmr.py` に追記:
```python
from diet.bmr import mifflin_st_jeor

def test_bmr_constants_male():
    # 70kg, 46歳, 169cm, male → 700 + 1056.25 - 230 + 5 = 1531.25
    result = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male")
    assert result == 1531.25

def test_bmr_female_offset():
    # female は male - 161 + 5 - 5 = male - 161
    male = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male")
    female = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="female")
    assert female == male - 161 - 5  # female は +(-161) = -161 (male の +5 と差し引き)

def test_bmr_invalid_sex_raises():
    import pytest
    with pytest.raises(ValueError):
        mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="other")

def test_bmr_height_169_constant_unfolded():
    """Regression: prior typo had 6.25 * 169 = 836.25 (correct: 1056.25)."""
    # 体重 0 / 年齢 0 / male / 身長 169 → 0 + 1056.25 - 0 + 5 = 1061.25
    assert mifflin_st_jeor(weight_kg=0.0, height_cm=169, age=0, sex="male") == 1061.25
```

- [ ] **Step 2: 失敗確認**

```bash
uv run pytest tests/test_bmr.py -v
```
Expected: ImportError on `mifflin_st_jeor`。

- [ ] **Step 3: 実装**

`src/diet/bmr.py` に追記:
```python
def mifflin_st_jeor(weight_kg: float, height_cm: int, age: int, sex: str) -> float:
    """Mifflin-St Jeor BMR (kcal/day)."""
    if sex == "male":
        sex_offset = 5
    elif sex == "female":
        sex_offset = -161
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    # 定数は spec § 3 に従い式そのまま、畳まない
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + sex_offset
```

- [ ] **Step 4: テストパス確認**

```bash
uv run pytest tests/test_bmr.py -v
```
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/bmr.py tests/test_bmr.py
git commit -m "feat(bmr): Mifflin-St Jeor with explicit constants"
```

---

### Task 1.3: intake.py — recorded_sum (op セマンティクス)

**Files:**
- Create: `src/diet/intake.py`
- Test: `tests/test_intake.py`

- [ ] **Step 1: テストを書く**

`tests/test_intake.py`:
```python
from datetime import datetime
from diet.intake import IntakeEvent, recorded_sum

def E(kcal: int, op: str, ts: str = "2026-05-25T12:00:00", id: int = 0) -> IntakeEvent:
    return IntakeEvent(id=id, timestamp=datetime.fromisoformat(ts), kcal=kcal, op=op)

def test_recorded_sum_empty():
    assert recorded_sum([]) is None

def test_recorded_sum_append_only():
    events = [E(500, "append"), E(300, "append")]
    assert recorded_sum(events) == 800

def test_recorded_sum_single_override():
    assert recorded_sum([E(2000, "override")]) == 2000

def test_recorded_sum_override_then_append():
    events = [E(500, "append"), E(2000, "override", ts="2026-05-25T13:00:00"),
              E(200, "append", ts="2026-05-25T14:00:00")]
    assert recorded_sum(events) == 2200

def test_recorded_sum_multiple_overrides_last_wins():
    events = [E(2000, "override", ts="2026-05-25T12:00:00"),
              E(1500, "override", ts="2026-05-25T13:00:00")]
    assert recorded_sum(events) == 1500

def test_recorded_sum_zero_fasting():
    assert recorded_sum([E(0, "override")]) == 0

def test_recorded_sum_deterministic_order_same_timestamp():
    # 同 timestamp は id ASC で安定化
    same_ts = "2026-05-25T12:00:00"
    events = [E(2000, "override", ts=same_ts, id=2),
              E(1500, "override", ts=same_ts, id=1)]
    # id=1 が先、id=2 が後 → 2000 (後勝ち)
    assert recorded_sum(events) == 2000
```

- [ ] **Step 2: 失敗確認**

```bash
uv run pytest tests/test_intake.py -v
```
Expected: ImportError。

- [ ] **Step 3: 実装**

`src/diet/intake.py`:
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class IntakeEvent:
    id: int
    timestamp: datetime
    kcal: int
    op: str  # 'append' or 'override'

def recorded_sum(events: list[IntakeEvent]) -> int | None:
    """Compute the recorded calorie sum for a day's events.

    Semantics:
      - empty -> None
      - last override resets baseline, subsequent appends add on top
      - append-only -> sum
      - deterministic order: timestamp ASC, id ASC
    """
    if not events:
        return None
    sorted_events = sorted(events, key=lambda e: (e.timestamp, e.id))
    last_override_idx = None
    for i, e in enumerate(sorted_events):
        if e.op == "override":
            last_override_idx = i
    if last_override_idx is None:
        return sum(e.kcal for e in sorted_events)
    baseline = sorted_events[last_override_idx].kcal
    appends_after = sum(e.kcal for e in sorted_events[last_override_idx + 1:] if e.op == "append")
    return baseline + appends_after
```

- [ ] **Step 4: テストパス確認**

```bash
uv run pytest tests/test_intake.py -v
```
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/intake.py tests/test_intake.py
git commit -m "feat(intake): recorded_sum honors op semantics + deterministic order"
```

---

### Task 1.4: intake.py — complete day 判定

**Files:**
- Modify: `src/diet/intake.py`
- Modify: `tests/test_intake.py`

- [ ] **Step 1: テストを追記**

```python
from diet.intake import is_complete_day

def test_complete_day_with_override():
    assert is_complete_day([E(2000, "override")]) is True

def test_complete_day_append_only_is_partial():
    assert is_complete_day([E(500, "append"), E(300, "append")]) is False

def test_complete_day_empty_is_false():
    assert is_complete_day([]) is False

def test_complete_day_mixed_with_override_is_true():
    assert is_complete_day([E(500, "append"), E(2000, "override")]) is True
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_intake.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/intake.py` に追記:
```python
def is_complete_day(events: list[IntakeEvent]) -> bool:
    """True if at least one event has op='override' (authoritative day)."""
    return any(e.op == "override" for e in events)
```

- [ ] **Step 4: テストパス確認**

`uv run pytest tests/test_intake.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/intake.py tests/test_intake.py
git commit -m "feat(intake): is_complete_day distinguishes authoritative from partial"
```

---

### Task 1.5: intake.py — past_avg (complete day only + sample floor + 半開区間)

**Files:**
- Modify: `src/diet/intake.py`
- Modify: `tests/test_intake.py`

- [ ] **Step 1: テストを追記**

```python
from datetime import date
from diet.intake import past_avg, DailyEvents, SAMPLE_FLOOR

def D(events_list: list[IntakeEvent]) -> DailyEvents:
    return DailyEvents(events=events_list)

def test_past_avg_empty_history():
    history: dict[date, DailyEvents] = {}
    assert past_avg(history, target_date=date(2026, 5, 25)) == (None, 0)

def test_past_avg_below_floor_returns_none():
    # complete day が 2 件のみ → floor=3 未達
    history = {
        date(2026, 5, 24): D([E(2000, "override")]),
        date(2026, 5, 23): D([E(1800, "override")]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg is None
    assert n == 2

def test_past_avg_at_floor_returns_average():
    history = {
        date(2026, 5, 24): D([E(2000, "override")]),
        date(2026, 5, 23): D([E(1800, "override")]),
        date(2026, 5, 22): D([E(2200, "override")]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3

def test_past_avg_excludes_partial_days():
    # complete 3 件 + partial 2 件 → complete のみ平均
    history = {
        date(2026, 5, 24): D([E(2000, "override")]),
        date(2026, 5, 23): D([E(1800, "override")]),
        date(2026, 5, 22): D([E(2200, "override")]),
        date(2026, 5, 21): D([E(500, "append")]),    # partial、除外
        date(2026, 5, 20): D([E(300, "append")]),    # partial、除外
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3

def test_past_avg_window_half_open_excludes_target_date():
    # target_date は含まない（半開区間）
    history = {
        date(2026, 5, 25): D([E(9999, "override")]),  # target_date 当日、除外
        date(2026, 5, 24): D([E(2000, "override")]),
        date(2026, 5, 23): D([E(1800, "override")]),
        date(2026, 5, 22): D([E(2200, "override")]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3  # 9999 が混ざってない証拠

def test_past_avg_window_half_open_includes_target_minus_14():
    # target_date - 14 は含む
    history = {
        date(2026, 5, 25 - 14): D([E(2000, "override")]),
        date(2026, 5, 25 - 13): D([E(1800, "override")]),
        date(2026, 5, 25 - 12): D([E(2200, "override")]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3

def test_past_avg_window_excludes_target_minus_15():
    # target_date - 15 は窓外
    history = {
        date(2026, 5, 25 - 15): D([E(9999, "override")]),  # 窓外、除外
        date(2026, 5, 25 - 14): D([E(2000, "override")]),
        date(2026, 5, 25 - 13): D([E(1800, "override")]),
        date(2026, 5, 25 - 12): D([E(2200, "override")]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3

def test_sample_floor_is_three():
    assert SAMPLE_FLOOR == 3
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_intake.py -v` → 新規 8 件 fail。

- [ ] **Step 3: 実装**

`src/diet/intake.py` に追記:
```python
from datetime import date, timedelta

SAMPLE_FLOOR = 3

@dataclass(frozen=True)
class DailyEvents:
    events: list[IntakeEvent]

def past_avg(
    history: dict[date, DailyEvents],
    target_date: date,
) -> tuple[float | None, int]:
    """Compute the past 14-day average over complete days only.

    Window: [target_date - 14 days, target_date) (half-open, JST dates).
    Returns (avg, n_samples).
    avg is None when n_samples < SAMPLE_FLOOR (even if a raw mean exists).
    """
    window_start = target_date - timedelta(days=14)
    complete_sums: list[int] = []
    for d, daily in history.items():
        if window_start <= d < target_date and is_complete_day(daily.events):
            s = recorded_sum(daily.events)
            if s is not None:
                complete_sums.append(s)
    n = len(complete_sums)
    if n < SAMPLE_FLOOR:
        return (None, n)
    return (sum(complete_sums) / n, n)
```

- [ ] **Step 4: テストパス確認**

`uv run pytest tests/test_intake.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/intake.py tests/test_intake.py
git commit -m "feat(intake): past_avg with sample floor and half-open window"
```

---

### Task 1.6: intake.py — decide_intake_kcal (7 ケース決定表)

**Files:**
- Modify: `src/diet/intake.py`
- Modify: `tests/test_intake.py`

- [ ] **Step 1: テストを書く（7 ケース網羅）**

```python
from diet.intake import decide_intake_kcal, IntakeDecision

def test_case1_complete_day_recorded_authoritative():
    d = decide_intake_kcal(
        today_events=[E(1800, "override")],
        past_avg_val=2000.0, n_samples=10,
        bootstrap_baseline=2200,
    )
    assert d.intake_kcal == 1800
    assert d.label == "recorded_authoritative"

def test_case1_fasting_day_zero_is_not_inflated():
    """★最重要回帰テスト: =0 が past_avg や baseline で水増しされない"""
    d = decide_intake_kcal(
        today_events=[E(0, "override")],
        past_avg_val=2200.0, n_samples=10,
        bootstrap_baseline=2000,
    )
    assert d.intake_kcal == 0
    assert d.label == "recorded_authoritative"

def test_case2_partial_recorded_high_with_avg():
    d = decide_intake_kcal(
        today_events=[E(2400, "append")],
        past_avg_val=2000.0, n_samples=10,
        bootstrap_baseline=None,
    )
    assert d.intake_kcal == 2400
    assert d.label == "recorded_partial_high"

def test_case2_partial_recorded_low_with_avg_supplemented():
    d = decide_intake_kcal(
        today_events=[E(500, "append")],
        past_avg_val=2100.0, n_samples=11,
        bootstrap_baseline=None,
    )
    assert d.intake_kcal == 2100
    assert d.label == "estimated_avg_supplement"
    assert d.recorded_part == 500
    assert d.supplement_part == 1600

def test_case3_partial_no_avg_baseline_supplemented():
    d = decide_intake_kcal(
        today_events=[E(500, "append")],
        past_avg_val=None, n_samples=2,
        bootstrap_baseline=2000,
    )
    assert d.intake_kcal == 2000
    assert d.label == "estimated_baseline_supplement"

def test_case4_partial_no_avg_no_baseline():
    d = decide_intake_kcal(
        today_events=[E(500, "append")],
        past_avg_val=None, n_samples=0,
        bootstrap_baseline=None,
    )
    assert d.intake_kcal == 500
    assert d.label == "recorded_no_baseline"

def test_case5_empty_with_avg_estimated():
    d = decide_intake_kcal(
        today_events=[],
        past_avg_val=1980.0, n_samples=8,
        bootstrap_baseline=2000,
    )
    assert d.intake_kcal == 1980
    assert d.label == "estimated_avg"

def test_case6_empty_no_avg_baseline_used():
    d = decide_intake_kcal(
        today_events=[],
        past_avg_val=None, n_samples=2,
        bootstrap_baseline=2000,
    )
    assert d.intake_kcal == 2000
    assert d.label == "estimated_baseline"

def test_case7_empty_no_avg_no_baseline_unconfirmed():
    d = decide_intake_kcal(
        today_events=[],
        past_avg_val=None, n_samples=0,
        bootstrap_baseline=None,
    )
    assert d.intake_kcal is None
    assert d.label == "unconfirmed"
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_intake.py -v` → 9 件 fail。

- [ ] **Step 3: 実装**

`src/diet/intake.py` に追記:
```python
@dataclass(frozen=True)
class IntakeDecision:
    intake_kcal: int | None
    label: str
    recorded_part: int | None = None
    supplement_part: int | None = None
    n_samples: int = 0

def decide_intake_kcal(
    today_events: list[IntakeEvent],
    past_avg_val: float | None,
    n_samples: int,
    bootstrap_baseline: int | None,
) -> IntakeDecision:
    """7-case decision per spec § 4.5. past_avg_val is treated as available
    only when it is not None (caller's past_avg() already enforced sample floor).
    """
    rec = recorded_sum(today_events)
    is_complete = is_complete_day(today_events)
    has_avg = past_avg_val is not None
    has_baseline = bootstrap_baseline is not None

    # Row 1: complete day is authoritative
    if is_complete:
        return IntakeDecision(intake_kcal=rec, label="recorded_authoritative", n_samples=n_samples)

    # today_events is None (empty) or partial
    if rec is not None:
        # partial day
        if has_avg:
            if rec >= past_avg_val:
                return IntakeDecision(intake_kcal=rec, label="recorded_partial_high", n_samples=n_samples)
            # Row 2: low partial supplemented by avg
            estimated = round(past_avg_val)
            return IntakeDecision(
                intake_kcal=estimated, label="estimated_avg_supplement",
                recorded_part=rec, supplement_part=estimated - rec, n_samples=n_samples,
            )
        if has_baseline:
            # Row 3: partial supplemented by baseline
            estimated = max(rec, bootstrap_baseline)
            return IntakeDecision(
                intake_kcal=estimated, label="estimated_baseline_supplement",
                recorded_part=rec, supplement_part=estimated - rec, n_samples=n_samples,
            )
        # Row 4: partial, no avg, no baseline
        return IntakeDecision(intake_kcal=rec, label="recorded_no_baseline", n_samples=n_samples)

    # empty day
    if has_avg:
        return IntakeDecision(intake_kcal=round(past_avg_val), label="estimated_avg", n_samples=n_samples)
    if has_baseline:
        return IntakeDecision(intake_kcal=bootstrap_baseline, label="estimated_baseline", n_samples=n_samples)
    # Row 7
    return IntakeDecision(intake_kcal=None, label="unconfirmed", n_samples=n_samples)
```

- [ ] **Step 4: テストパス確認**

`uv run pytest tests/test_intake.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/intake.py tests/test_intake.py
git commit -m "feat(intake): 7-case decision table with =0 fasting protection"
```

---

### Task 1.7: intake.py — 統合回帰テスト（断食日が水増しされない E2E）

**Files:**
- Create: `tests/test_intake_regression.py`

- [ ] **Step 1: テスト**

```python
from datetime import date
from diet.intake import (
    IntakeEvent, DailyEvents, past_avg, decide_intake_kcal,
)
from datetime import datetime

def E(kcal, op, day):
    return IntakeEvent(id=0, timestamp=datetime(day.year, day.month, day.day, 12, 0), kcal=kcal, op=op)

def test_fasting_day_after_normal_history_stays_zero():
    """全行程: 14 日間 complete day で 2200 平均、target=断食日 =0 → 0 のまま出る"""
    history = {
        date(2026, 5, 25 - i): DailyEvents(events=[E(2200, "override", date(2026, 5, 25 - i))])
        for i in range(1, 15)  # day -1 .. day -14
    }
    target = date(2026, 5, 25)
    today_events = [E(0, "override", target)]

    avg, n = past_avg(history, target)
    assert n == 14
    assert avg == 2200.0

    d = decide_intake_kcal(today_events, avg, n, bootstrap_baseline=2000)
    assert d.intake_kcal == 0  # ★ 水増しされない
    assert d.label == "recorded_authoritative"

def test_low_calorie_complete_day_stays_low():
    """=1200 制限日が 2200 平均で 2200 になったりしない"""
    history = {
        date(2026, 5, 25 - i): DailyEvents(events=[E(2200, "override", date(2026, 5, 25 - i))])
        for i in range(1, 15)
    }
    target = date(2026, 5, 25)
    today_events = [E(1200, "override", target)]
    avg, n = past_avg(history, target)
    d = decide_intake_kcal(today_events, avg, n, bootstrap_baseline=2000)
    assert d.intake_kcal == 1200
```

- [ ] **Step 2: 実行**

`uv run pytest tests/test_intake_regression.py -v` → passed (実装は Task 1.6 で済んでいる)。

- [ ] **Step 3: Commit**

```bash
git add tests/test_intake_regression.py
git commit -m "test(intake): regression test for fasting/restriction days"
```

---

## Phase 2: ストレージ (db.py)

### Task 2.1: db.py — SQLite スキーマ migration

**Files:**
- Create: `src/diet/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: テスト**

```python
import sqlite3
from pathlib import Path
from diet.db import open_db, MIGRATION_SQL

def test_open_db_creates_all_tables(tmp_path: Path):
    conn = open_db(tmp_path / "test.db")
    cur = conn.cursor()
    tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {"config", "intake_events", "daily_activity", "daily_weight", "fitbit_token", "_meta"}
    assert expected.issubset(tables)

def test_open_db_idempotent(tmp_path: Path):
    db_path = tmp_path / "test.db"
    open_db(db_path).close()
    open_db(db_path).close()  # second open should not error

def test_config_table_single_row_constraint(tmp_path: Path):
    conn = open_db(tmp_path / "test.db")
    conn.execute("INSERT INTO config (id, birthday, height_cm, sex, timezone) VALUES (1, '1979-12-01', 169, 'male', 'Asia/Tokyo')")
    conn.commit()
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO config (id, birthday, height_cm, sex, timezone) VALUES (2, '2000-01-01', 170, 'male', 'Asia/Tokyo')")
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_db.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/db.py`:
```python
import sqlite3
from pathlib import Path

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS _meta (
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  birthday TEXT NOT NULL,
  height_cm INTEGER NOT NULL,
  sex TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'Asia/Tokyo',
  hpasaneel_path TEXT,
  hpasaneel_diet_root TEXT DEFAULT 'content/diet',
  exercise_calorie_source TEXT,
  bootstrap_daily_kcal INTEGER
);

CREATE TABLE IF NOT EXISTS intake_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  kcal INTEGER NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('append', 'override')),
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_intake_events_date ON intake_events(date);

CREATE TABLE IF NOT EXISTS daily_activity (
  date TEXT PRIMARY KEY,
  steps INTEGER NOT NULL,
  distance_km REAL NOT NULL,
  logged_activities_kcal INTEGER,
  marginal_kcal INTEGER,
  last_synced TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_weight (
  date TEXT PRIMARY KEY,
  weight_kg REAL NOT NULL,
  last_synced TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fitbit_token (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  access_token TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_id TEXT NOT NULL,
  rotated_at TEXT NOT NULL
);

INSERT INTO _meta (schema_version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM _meta);
"""

def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(MIGRATION_SQL)
    conn.commit()
    return conn
```

- [ ] **Step 4: テストパス**

`uv run pytest tests/test_db.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/db.py tests/test_db.py
git commit -m "feat(db): SQLite schema with single-row constraints on config/token"
```

---

### Task 2.2: db.py — CRUD ヘルパー (intake_events / daily_activity / daily_weight)

**Files:**
- Modify: `src/diet/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: テスト追記**

```python
from datetime import datetime, date
from diet.db import (
    insert_intake_event, get_events_for_date, get_events_in_range,
    upsert_daily_activity, get_daily_activity,
    upsert_daily_weight, get_latest_weight_on_or_before,
)

def test_intake_event_round_trip(tmp_path):
    conn = open_db(tmp_path / "t.db")
    insert_intake_event(conn, date(2026, 5, 25), datetime(2026, 5, 25, 12, 0), 500, "append", note="ラーメン")
    events = get_events_for_date(conn, date(2026, 5, 25))
    assert len(events) == 1
    assert events[0].kcal == 500
    assert events[0].op == "append"

def test_get_events_in_range_half_open(tmp_path):
    conn = open_db(tmp_path / "t.db")
    for offset in [0, 1, 14, 15]:
        d = date(2026, 5, 25) - __import__("datetime").timedelta(days=offset)
        insert_intake_event(conn, d, datetime(d.year, d.month, d.day, 12, 0), 100 * offset, "override")
    history = get_events_in_range(conn, start=date(2026, 5, 25) - __import__("datetime").timedelta(days=14), end=date(2026, 5, 25))
    dates_in = sorted(history.keys())
    # [target - 14, target) なので offset 1..14 が入り、0 と 15 は除外
    assert date(2026, 5, 25 - 14) in history
    assert date(2026, 5, 25 - 15) not in history
    assert date(2026, 5, 25) not in history  # half-open end

def test_daily_activity_upsert(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_daily_activity(conn, date(2026, 5, 25), steps=8234, distance_km=5.3, logged_activities_kcal=280, marginal_kcal=340)
    a = get_daily_activity(conn, date(2026, 5, 25))
    assert a.steps == 8234
    upsert_daily_activity(conn, date(2026, 5, 25), steps=9000, distance_km=6.0, logged_activities_kcal=300, marginal_kcal=360)
    a = get_daily_activity(conn, date(2026, 5, 25))
    assert a.steps == 9000  # 上書き

def test_latest_weight_on_or_before(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_daily_weight(conn, date(2026, 5, 20), 72.0)
    upsert_daily_weight(conn, date(2026, 5, 22), 71.5)
    w = get_latest_weight_on_or_before(conn, date(2026, 5, 25))
    assert w.weight_kg == 71.5
    assert w.date == date(2026, 5, 22)
    # target_date 未来の体重は使わない（タイムマシン禁止）
    upsert_daily_weight(conn, date(2026, 5, 26), 71.0)
    w2 = get_latest_weight_on_or_before(conn, date(2026, 5, 25))
    assert w2.weight_kg == 71.5  # 71.0 は使われない
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_db.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/db.py` に追記:
```python
from dataclasses import dataclass
from datetime import date, datetime
from diet.intake import IntakeEvent, DailyEvents

def _date_str(d: date) -> str:
    return d.isoformat()

def insert_intake_event(
    conn: sqlite3.Connection,
    d: date, ts: datetime, kcal: int, op: str, note: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO intake_events (date, timestamp, kcal, op, note) VALUES (?, ?, ?, ?, ?)",
        (_date_str(d), ts.isoformat(), kcal, op, note),
    )
    conn.commit()
    return cur.lastrowid

def get_events_for_date(conn: sqlite3.Connection, d: date) -> list[IntakeEvent]:
    rows = conn.execute(
        "SELECT id, timestamp, kcal, op FROM intake_events WHERE date = ? ORDER BY timestamp ASC, id ASC",
        (_date_str(d),),
    ).fetchall()
    return [IntakeEvent(id=r[0], timestamp=datetime.fromisoformat(r[1]), kcal=r[2], op=r[3]) for r in rows]

def get_events_in_range(conn: sqlite3.Connection, start: date, end: date) -> dict[date, DailyEvents]:
    """Half-open: [start, end). Used by past_avg()."""
    rows = conn.execute(
        "SELECT id, date, timestamp, kcal, op FROM intake_events WHERE date >= ? AND date < ? ORDER BY date, timestamp, id",
        (_date_str(start), _date_str(end)),
    ).fetchall()
    result: dict[date, list[IntakeEvent]] = {}
    for r in rows:
        d = date.fromisoformat(r[1])
        result.setdefault(d, []).append(IntakeEvent(id=r[0], timestamp=datetime.fromisoformat(r[2]), kcal=r[3], op=r[4]))
    return {d: DailyEvents(events=ev) for d, ev in result.items()}

@dataclass(frozen=True)
class DailyActivityRow:
    date: date
    steps: int
    distance_km: float
    logged_activities_kcal: int | None
    marginal_kcal: int | None

def upsert_daily_activity(conn, d: date, steps: int, distance_km: float,
                          logged_activities_kcal: int | None, marginal_kcal: int | None) -> None:
    conn.execute(
        """INSERT INTO daily_activity (date, steps, distance_km, logged_activities_kcal, marginal_kcal, last_synced)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             steps=excluded.steps, distance_km=excluded.distance_km,
             logged_activities_kcal=excluded.logged_activities_kcal,
             marginal_kcal=excluded.marginal_kcal,
             last_synced=excluded.last_synced""",
        (_date_str(d), steps, distance_km, logged_activities_kcal, marginal_kcal, datetime.now().isoformat()),
    )
    conn.commit()

def get_daily_activity(conn, d: date) -> DailyActivityRow | None:
    row = conn.execute(
        "SELECT date, steps, distance_km, logged_activities_kcal, marginal_kcal FROM daily_activity WHERE date = ?",
        (_date_str(d),),
    ).fetchone()
    if row is None:
        return None
    return DailyActivityRow(date=date.fromisoformat(row[0]), steps=row[1], distance_km=row[2],
                            logged_activities_kcal=row[3], marginal_kcal=row[4])

@dataclass(frozen=True)
class DailyWeightRow:
    date: date
    weight_kg: float

def upsert_daily_weight(conn, d: date, weight_kg: float) -> None:
    conn.execute(
        """INSERT INTO daily_weight (date, weight_kg, last_synced) VALUES (?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET weight_kg=excluded.weight_kg, last_synced=excluded.last_synced""",
        (_date_str(d), weight_kg, datetime.now().isoformat()),
    )
    conn.commit()

def get_latest_weight_on_or_before(conn, d: date) -> DailyWeightRow | None:
    row = conn.execute(
        "SELECT date, weight_kg FROM daily_weight WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (_date_str(d),),
    ).fetchone()
    if row is None:
        return None
    return DailyWeightRow(date=date.fromisoformat(row[0]), weight_kg=row[1])
```

- [ ] **Step 4: テストパス確認**

`uv run pytest tests/test_db.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/db.py tests/test_db.py
git commit -m "feat(db): CRUD helpers with half-open range + weight time-machine protection"
```

---

### Task 2.3: db.py — config と token の CRUD + atomic rotation

**Files:**
- Modify: `src/diet/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: テスト追記**

```python
from diet.db import (
    save_config, load_config, save_token_atomic, load_token, Config, Token,
)
from datetime import datetime, timedelta

def test_config_save_load(tmp_path):
    conn = open_db(tmp_path / "t.db")
    cfg = Config(birthday=date(1979, 12, 1), height_cm=169, sex="male", timezone="Asia/Tokyo",
                 hpasaneel_path="C:/code/HPasaneel", hpasaneel_diet_root="content/diet",
                 exercise_calorie_source="marginal", bootstrap_daily_kcal=2000)
    save_config(conn, cfg)
    loaded = load_config(conn)
    assert loaded == cfg

def test_token_atomic_rotation(tmp_path):
    conn = open_db(tmp_path / "t.db")
    tok1 = Token(access_token="A1", refresh_token="R1",
                 expires_at=datetime(2026, 12, 31), user_id="UID")
    save_token_atomic(conn, tok1)
    assert load_token(conn) == tok1
    tok2 = Token(access_token="A2", refresh_token="R2",
                 expires_at=datetime(2027, 1, 1), user_id="UID")
    save_token_atomic(conn, tok2)
    assert load_token(conn) == tok2  # 完全置換、id=1 行は 1 つだけ
    n = conn.execute("SELECT COUNT(*) FROM fitbit_token").fetchone()[0]
    assert n == 1
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_db.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/db.py` に追記:
```python
@dataclass(frozen=True)
class Config:
    birthday: date
    height_cm: int
    sex: str
    timezone: str
    hpasaneel_path: str | None
    hpasaneel_diet_root: str
    exercise_calorie_source: str | None
    bootstrap_daily_kcal: int | None

def save_config(conn, cfg: Config) -> None:
    conn.execute(
        """INSERT INTO config (id, birthday, height_cm, sex, timezone, hpasaneel_path,
                              hpasaneel_diet_root, exercise_calorie_source, bootstrap_daily_kcal)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             birthday=excluded.birthday, height_cm=excluded.height_cm, sex=excluded.sex,
             timezone=excluded.timezone, hpasaneel_path=excluded.hpasaneel_path,
             hpasaneel_diet_root=excluded.hpasaneel_diet_root,
             exercise_calorie_source=excluded.exercise_calorie_source,
             bootstrap_daily_kcal=excluded.bootstrap_daily_kcal""",
        (cfg.birthday.isoformat(), cfg.height_cm, cfg.sex, cfg.timezone, cfg.hpasaneel_path,
         cfg.hpasaneel_diet_root, cfg.exercise_calorie_source, cfg.bootstrap_daily_kcal),
    )
    conn.commit()

def load_config(conn) -> Config | None:
    row = conn.execute(
        "SELECT birthday, height_cm, sex, timezone, hpasaneel_path, hpasaneel_diet_root, "
        "exercise_calorie_source, bootstrap_daily_kcal FROM config WHERE id=1"
    ).fetchone()
    if row is None:
        return None
    return Config(birthday=date.fromisoformat(row[0]), height_cm=row[1], sex=row[2], timezone=row[3],
                  hpasaneel_path=row[4], hpasaneel_diet_root=row[5],
                  exercise_calorie_source=row[6], bootstrap_daily_kcal=row[7])

@dataclass(frozen=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: datetime
    user_id: str

def save_token_atomic(conn, tok: Token) -> None:
    """BEGIN IMMEDIATE で他プロセスと排他、全置換、commit。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM fitbit_token")
        conn.execute(
            "INSERT INTO fitbit_token (id, access_token, refresh_token, expires_at, user_id, rotated_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (tok.access_token, tok.refresh_token, tok.expires_at.isoformat(), tok.user_id, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def load_token(conn) -> Token | None:
    row = conn.execute(
        "SELECT access_token, refresh_token, expires_at, user_id FROM fitbit_token WHERE id=1"
    ).fetchone()
    if row is None:
        return None
    return Token(access_token=row[0], refresh_token=row[1],
                 expires_at=datetime.fromisoformat(row[2]), user_id=row[3])
```

- [ ] **Step 4: テストパス**

`uv run pytest tests/test_db.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/db.py tests/test_db.py
git commit -m "feat(db): atomic token rotation with BEGIN IMMEDIATE"
```

---

## Phase 3: OAuth + Fitbit クライアント

### Task 3.1: oauth.py — 自己署名 TLS 証明書生成

**Files:**
- Create: `src/diet/oauth.py`
- Create: `tests/test_oauth.py`

- [ ] **Step 1: テスト**

```python
from pathlib import Path
from diet.oauth import generate_self_signed_cert

def test_generate_cert_creates_files(tmp_path: Path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    generate_self_signed_cert(cert_path=cert, key_path=key, hostname="localhost", days_valid=3650)
    assert cert.exists()
    assert key.exists()
    assert cert.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert key.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")

def test_generate_cert_idempotent_if_files_exist(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    generate_self_signed_cert(cert, key, "localhost", 3650)
    original_cert = cert.read_bytes()
    generate_self_signed_cert(cert, key, "localhost", 3650)  # 再呼び出しで上書きしない
    assert cert.read_bytes() == original_cert
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_oauth.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/oauth.py`:
```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

def generate_self_signed_cert(
    cert_path: Path, key_path: Path, hostname: str = "localhost", days_valid: int = 3650,
) -> None:
    """Create self-signed TLS cert + key (PEM). No-op if both files already exist."""
    if cert_path.exists() and key_path.exists():
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=days_valid))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
```

- [ ] **Step 4: テストパス**

`uv run pytest tests/test_oauth.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/oauth.py tests/test_oauth.py
git commit -m "feat(oauth): self-signed TLS cert generation"
```

---

### Task 3.2: oauth.py — HTTPS callback サーバー + auth URL ビルド

**Files:**
- Modify: `src/diet/oauth.py`
- Modify: `tests/test_oauth.py`

- [ ] **Step 1: テスト**

```python
from diet.oauth import build_authorization_url, FITBIT_AUTHZ_URL

def test_build_authorization_url_includes_required_params():
    url = build_authorization_url(
        client_id="23ABCD",
        redirect_uri="https://localhost:8765/callback",
        scopes=["activity", "weight"],
        state="randomstate123",
    )
    assert url.startswith(FITBIT_AUTHZ_URL)
    assert "client_id=23ABCD" in url
    assert "response_type=code" in url
    assert "redirect_uri=https%3A%2F%2Flocalhost%3A8765%2Fcallback" in url
    assert "scope=activity+weight" in url or "scope=activity%20weight" in url
    assert "state=randomstate123" in url
```

(callback server 自体の単体テストは複雑なので結合テスト側でカバー。ここはビルド関数のみ。)

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_oauth.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/oauth.py` に追記:
```python
import http.server
import ssl
import threading
import urllib.parse
from dataclasses import dataclass

FITBIT_AUTHZ_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"

def build_authorization_url(
    client_id: str, redirect_uri: str, scopes: list[str], state: str,
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{FITBIT_AUTHZ_URL}?{urllib.parse.urlencode(params)}"

@dataclass
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None

def run_callback_server(cert_path: Path, key_path: Path, port: int = 8765, timeout_sec: int = 300) -> CallbackResult:
    """Listen for the OAuth redirect once, then shut down. Returns parsed code/state."""
    result = CallbackResult()
    finished = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404); self.end_headers(); return
            qs = urllib.parse.parse_qs(parsed.query)
            result.code = (qs.get("code") or [None])[0]
            result.state = (qs.get("state") or [None])[0]
            result.error = (qs.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization received</h1><p>You can close this tab.</p>")
            finished.set()
        def log_message(self, fmt, *args): pass

    httpd = http.server.HTTPServer(("localhost", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    finished.wait(timeout=timeout_sec)
    httpd.shutdown()
    return result
```

- [ ] **Step 4: テストパス**

`uv run pytest tests/test_oauth.py -v` → passed (build only)。

- [ ] **Step 5: Commit**

```bash
git add src/diet/oauth.py tests/test_oauth.py
git commit -m "feat(oauth): HTTPS callback server + auth URL builder"
```

---

### Task 3.3: oauth.py — token 交換 (auth code → access/refresh token)

**Files:**
- Modify: `src/diet/oauth.py`
- Modify: `tests/test_oauth.py`

- [ ] **Step 1: テスト (httpx mock)**

```python
import pytest
import httpx
from diet.oauth import exchange_code_for_token, refresh_access_token

@pytest.mark.asyncio
async def test_exchange_code_for_token_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token",
        method="POST",
        json={
            "access_token": "A1", "refresh_token": "R1",
            "expires_in": 28800, "user_id": "UID", "scope": "activity weight",
        },
    )
    tok = await exchange_code_for_token(
        client_id="CID", client_secret="CSEC", code="C1", redirect_uri="https://localhost:8765/callback",
    )
    assert tok.access_token == "A1"
    assert tok.refresh_token == "R1"
    assert tok.user_id == "UID"

@pytest.mark.asyncio
async def test_refresh_returns_new_pair(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token",
        method="POST",
        json={"access_token": "A2", "refresh_token": "R2", "expires_in": 28800,
              "user_id": "UID", "scope": "activity weight"},
    )
    tok = await refresh_access_token(client_id="CID", client_secret="CSEC", refresh_token="R1")
    assert tok.access_token == "A2"
    assert tok.refresh_token == "R2"
```

注: pytest-httpx は async client を mock するので、関数は `async def` で書く。

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_oauth.py -v` → ImportError。

- [ ] **Step 3: 実装**

`src/diet/oauth.py` に追記:
```python
import base64
from datetime import datetime, timedelta
import httpx
from diet.db import Token

async def exchange_code_for_token(
    client_id: str, client_secret: str, code: str, redirect_uri: str,
) -> Token:
    return await _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }, client_id, client_secret)

async def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Token:
    return await _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, client_id, client_secret)

async def _token_request(data: dict, client_id: str, client_secret: str) -> Token:
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(FITBIT_TOKEN_URL, data=data, headers=headers, timeout=30.0)
        r.raise_for_status()
        body = r.json()
    return Token(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=datetime.now() + timedelta(seconds=int(body["expires_in"])),
        user_id=body["user_id"],
    )
```

- [ ] **Step 4: テストパス**

```bash
uv run pytest tests/test_oauth.py -v
```
Expected: 全 passed (要 `pytest-asyncio` 追加 → pyproject の dev deps に `pytest-asyncio>=0.23` を加える、`[tool.pytest.ini_options]` に `asyncio_mode = "auto"` を追加)。

実装中に asyncio エラーが出たら pyproject.toml を更新し `uv sync` → 再実行。

- [ ] **Step 5: Commit**

```bash
git add src/diet/oauth.py tests/test_oauth.py pyproject.toml
git commit -m "feat(oauth): token exchange and refresh via Fitbit token endpoint"
```

---

## Phase 4: Fitbit クライアント

### Task 4.1: fitbit_client.py — 認証付き HTTP + rate limit 追跡

**Files:**
- Create: `src/diet/fitbit_client.py`
- Create: `tests/test_fitbit_client.py`

- [ ] **Step 1: テスト**

```python
import pytest
from diet.fitbit_client import FitbitClient, RateLimitState

@pytest.mark.asyncio
async def test_authorization_header_set(httpx_mock):
    httpx_mock.add_response(url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
                            json={"summary": {"steps": 100}}, match_headers={"Authorization": "Bearer A1"})
    client = FitbitClient(access_token="A1")
    data = await client.get_activity_summary("2026-05-25")
    assert data["summary"]["steps"] == 100

@pytest.mark.asyncio
async def test_rate_limit_headers_tracked(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        json={}, headers={"Fitbit-Rate-Limit-Limit": "150",
                          "Fitbit-Rate-Limit-Remaining": "120",
                          "Fitbit-Rate-Limit-Reset": "1800"},
    )
    client = FitbitClient(access_token="A1")
    await client.get_activity_summary("2026-05-25")
    assert client.rate_limit.limit == 150
    assert client.rate_limit.remaining == 120
    assert client.rate_limit.reset_seconds == 1800
```

- [ ] **Step 2: 失敗確認 → 実装 → パス → Commit**

`src/diet/fitbit_client.py`:
```python
from dataclasses import dataclass, field
import httpx

@dataclass
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_seconds: int | None = None

class FitbitClient:
    BASE = "https://api.fitbit.com"
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.rate_limit = RateLimitState()

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _update_rate_limit(self, headers: httpx.Headers) -> None:
        if "Fitbit-Rate-Limit-Limit" in headers:
            self.rate_limit.limit = int(headers["Fitbit-Rate-Limit-Limit"])
        if "Fitbit-Rate-Limit-Remaining" in headers:
            self.rate_limit.remaining = int(headers["Fitbit-Rate-Limit-Remaining"])
        if "Fitbit-Rate-Limit-Reset" in headers:
            self.rate_limit.reset_seconds = int(headers["Fitbit-Rate-Limit-Reset"])

    async def get_activity_summary(self, date_str: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.BASE}/1/user/-/activities/date/{date_str}.json",
                                 headers=self._headers(), timeout=30.0)
            self._update_rate_limit(r.headers)
            r.raise_for_status()
            return r.json()
```

```bash
uv run pytest tests/test_fitbit_client.py -v
git add src/diet/fitbit_client.py tests/test_fitbit_client.py
git commit -m "feat(fitbit): authorized client with rate-limit tracking"
```

---

### Task 4.2: fitbit_client.py — weight endpoint + 401 自動 refresh

**Files:**
- Modify: `src/diet/fitbit_client.py`
- Modify: `tests/test_fitbit_client.py`

- [ ] **Step 1: テスト**

```python
@pytest.mark.asyncio
async def test_get_weight_log(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/body/log/weight/date/2026-05-25.json",
        json={"weight": [{"date": "2026-05-25", "weight": 71.2, "time": "07:30:00"}]},
    )
    client = FitbitClient(access_token="A1")
    weights = await client.get_weight_log("2026-05-25")
    assert weights[0]["weight"] == 71.2

@pytest.mark.asyncio
async def test_401_triggers_single_refresh(httpx_mock):
    # 1 回目 401、2 回目 200
    httpx_mock.add_response(status_code=401)
    httpx_mock.add_response(json={"summary": {"steps": 100}})
    refresh_called = {"n": 0}
    async def fake_refresh():
        refresh_called["n"] += 1
        return "A2"
    client = FitbitClient(access_token="A1", on_unauthorized=fake_refresh)
    data = await client.get_activity_summary("2026-05-25")
    assert refresh_called["n"] == 1
    assert client.access_token == "A2"
    assert data["summary"]["steps"] == 100
```

- [ ] **Step 2: 失敗確認**

`uv run pytest tests/test_fitbit_client.py -v` → fail。

- [ ] **Step 3: 実装**

`src/diet/fitbit_client.py` 修正:
```python
class FitbitClient:
    def __init__(self, access_token: str, on_unauthorized=None):
        self.access_token = access_token
        self.rate_limit = RateLimitState()
        self.on_unauthorized = on_unauthorized

    async def _request(self, method: str, url: str) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            r = await client.request(method, url, headers=self._headers(), timeout=30.0)
            self._update_rate_limit(r.headers)
            if r.status_code == 401 and self.on_unauthorized:
                self.access_token = await self.on_unauthorized()
                async with httpx.AsyncClient() as client2:
                    r = await client2.request(method, url, headers=self._headers(), timeout=30.0)
                    self._update_rate_limit(r.headers)
            r.raise_for_status()
            return r

    async def get_activity_summary(self, date_str: str) -> dict:
        r = await self._request("GET", f"{self.BASE}/1/user/-/activities/date/{date_str}.json")
        return r.json()

    async def get_weight_log(self, date_str: str) -> list[dict]:
        r = await self._request("GET", f"{self.BASE}/1/user/-/body/log/weight/date/{date_str}.json")
        return r.json().get("weight", [])
```

- [ ] **Step 4: テストパス → Commit**

```bash
uv run pytest tests/test_fitbit_client.py -v
git add src/diet/fitbit_client.py tests/test_fitbit_client.py
git commit -m "feat(fitbit): weight endpoint + single 401 retry with token refresh"
```

---

## Phase 5: publish.py (公開境界)

### Task 5.1: publish.py — DTO + to_public_dict

**Files:**
- Create: `src/diet/publish.py`
- Create: `tests/test_publish_boundary.py`

- [ ] **Step 1: テスト**

```python
from datetime import date
from diet.publish import PublicDayRecord

def test_public_record_to_dict_has_only_5_keys():
    r = PublicDayRecord(date=date(2026, 5, 25), steps=8234, distance_km=5.3,
                        exercise_kcal=280, weight_kg=71.2)
    d = r.to_public_dict()
    assert set(d.keys()) == {"date", "steps", "distance_km", "exercise_kcal", "weight_kg"}
    assert d["date"] == "2026-05-25"

def test_public_record_handles_missing_weight():
    """体重未取得日は weight_kg=None 不可。spec 上は必須なので validation で落とす想定。
    呼び出し側で None なら build_log_json でスキップする。"""
    # ここでは null 不許可型なので int/float 必須
    pass
```

- [ ] **Step 2: 失敗確認 → 実装 → パス → Commit**

`src/diet/publish.py`:
```python
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class PublicDayRecord:
    date: date
    steps: int
    distance_km: float
    exercise_kcal: int
    weight_kg: float

    def to_public_dict(self) -> dict:
        """Hand-written, NEVER use asdict/__dict__ — must enforce field allowlist."""
        return {
            "date": self.date.isoformat(),
            "steps": self.steps,
            "distance_km": self.distance_km,
            "exercise_kcal": self.exercise_kcal,
            "weight_kg": self.weight_kg,
        }
```

```bash
uv run pytest tests/test_publish_boundary.py -v
git add src/diet/publish.py tests/test_publish_boundary.py
git commit -m "feat(publish): PublicDayRecord DTO with hand-written allowlist serializer"
```

---

### Task 5.2: publish.py — JSON schema + 2 段 validate

**Files:**
- Modify: `src/diet/publish.py`
- Create: `tests/test_publish_schema.py`

- [ ] **Step 1: テスト**

```python
import pytest
from diet.publish import validate_log_json, build_log_json, PublicDayRecord
from datetime import date, datetime, timezone

def test_validates_minimal_valid():
    doc = {"updated_at": "2026-05-25T22:00:00+09:00",
           "days": [{"date": "2026-05-25", "steps": 8234, "distance_km": 5.3,
                     "exercise_kcal": 280, "weight_kg": 71.2}]}
    validate_log_json(doc)  # 例外出なければ OK

def test_validate_rejects_extra_top_level_field():
    doc = {"updated_at": "2026-05-25T22:00:00+09:00", "days": [], "leaked_field": "secret"}
    with pytest.raises(Exception):
        validate_log_json(doc)

def test_validate_rejects_extra_day_field():
    """note フィールドが混入したら絶対 reject"""
    doc = {"updated_at": "2026-05-25T22:00:00+09:00",
           "days": [{"date": "2026-05-25", "steps": 100, "distance_km": 1.0,
                     "exercise_kcal": 50, "weight_kg": 70.0, "note": "ラーメン特盛"}]}
    with pytest.raises(Exception):
        validate_log_json(doc)

def test_validate_rejects_missing_required():
    doc = {"updated_at": "2026-05-25T22:00:00+09:00",
           "days": [{"date": "2026-05-25", "steps": 100}]}
    with pytest.raises(Exception):
        validate_log_json(doc)

def test_build_log_json_calls_validate(monkeypatch):
    calls = []
    import diet.publish as p
    orig = p.validate_log_json
    def spy(d): calls.append(d); return orig(d)
    monkeypatch.setattr(p, "validate_log_json", spy)
    records = [PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=1.0)]
    p.build_log_json(records, existing_doc=None)
    assert len(calls) >= 1  # 書き出し前 validate が呼ばれる
```

- [ ] **Step 2: 失敗確認 → 実装 → パス → Commit**

`src/diet/publish.py` に追記:
```python
import jsonschema
from datetime import datetime, timezone

LOG_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["updated_at", "days"],
    "properties": {
        "updated_at": {"type": "string", "format": "date-time"},
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["date", "steps", "distance_km", "exercise_kcal", "weight_kg"],
                "properties": {
                    "date":          {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "steps":         {"type": "integer", "minimum": 0},
                    "distance_km":   {"type": "number", "minimum": 0},
                    "exercise_kcal": {"type": "integer", "minimum": 0},
                    "weight_kg":     {"type": "number", "minimum": 0},
                },
            },
        },
    },
}

def validate_log_json(doc: dict) -> None:
    """Raises jsonschema.ValidationError on any violation."""
    jsonschema.validate(doc, LOG_JSON_SCHEMA)

def build_log_json(records: list[PublicDayRecord], existing_doc: dict | None) -> dict:
    """Merge new records into existing_doc, replacing matching dates.
    Performs validation on existing_doc (raw load), again on final output.
    Caller is responsible for actually reading existing_doc from disk.
    """
    if existing_doc is not None:
        validate_log_json(existing_doc)  # 段 1: raw load
        existing_by_date = {d["date"]: d for d in existing_doc["days"]}
    else:
        existing_by_date = {}
    for r in records:
        existing_by_date[r.date.isoformat()] = r.to_public_dict()
    final = {
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "days": sorted(existing_by_date.values(), key=lambda d: d["date"], reverse=True),
    }
    validate_log_json(final)  # 段 2: 書き出し前
    return final
```

```bash
uv run pytest tests/test_publish_schema.py -v
git add src/diet/publish.py tests/test_publish_schema.py
git commit -m "feat(publish): 2-stage JSON schema validation (raw load + final)"
```

---

### Task 5.3: publish.py — 境界テスト（note 漏洩検査）

**Files:**
- Modify: `tests/test_publish_boundary.py`

- [ ] **Step 1: テスト**

```python
from datetime import date
from diet.publish import PublicDayRecord, build_log_json
import json

def test_no_note_text_in_final_json():
    """★最重要: メニュー名が log.json の文字列に絶対出現しない"""
    record = PublicDayRecord(date=date(2026, 5, 25), steps=8000,
                             distance_km=5.0, exercise_kcal=300, weight_kg=71.2)
    out = build_log_json([record], existing_doc=None)
    serialized = json.dumps(out, ensure_ascii=False)
    # 食事 note の代表的文字列が一切出ないこと
    for forbidden in ["ラーメン", "焼肉", "ホルモン", "ピザ", "ケーキ", "intake", "kcal_intake", "note"]:
        assert forbidden not in serialized, f"forbidden token '{forbidden}' leaked into log.json"

def test_no_intake_kcal_in_final_json():
    record = PublicDayRecord(date=date(2026, 5, 25), steps=8000,
                             distance_km=5.0, exercise_kcal=300, weight_kg=71.2)
    out = build_log_json([record], existing_doc=None)
    serialized = json.dumps(out)
    # 摂取系のフィールド名が一切出ない
    assert "intake" not in serialized
```

- [ ] **Step 2: テスト実行**

`uv run pytest tests/test_publish_boundary.py -v` → passed (実装は既存)。

- [ ] **Step 3: Commit**

```bash
git add tests/test_publish_boundary.py
git commit -m "test(publish): boundary test ensures menu names never reach log.json"
```

---

### Task 5.4: publish.py — git 操作ラッパー

**Files:**
- Modify: `src/diet/publish.py`
- Create: `tests/test_publish_git.py`

- [ ] **Step 1: テスト (subprocess を mock)**

```python
import subprocess
from pathlib import Path
from diet.publish import publish_to_hpasaneel, PublicDayRecord
from datetime import date

def test_publish_writes_json_and_runs_git(tmp_path, monkeypatch):
    """既存 HPasaneel リポジトリを模擬: tmp_path/HPasaneel/content/diet/log.json"""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    # 最初のダミーコミット (HEAD を作る)
    (repo / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    record = PublicDayRecord(date=date(2026, 5, 25), steps=1000, distance_km=1.0,
                             exercise_kcal=50, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [record], do_push=False)

    log_path = repo / "content/diet/log.json"
    assert log_path.exists()
    assert "2026-05-25" in log_path.read_text()
    # commit があるか確認
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, check=True, capture_output=True, text=True)
    assert "diet: 2026-05-25" in log.stdout
```

- [ ] **Step 2: 失敗確認 → 実装 → パス → Commit**

`src/diet/publish.py` に追記:
```python
import json
import subprocess
from pathlib import Path

def publish_to_hpasaneel(
    repo_path: Path, diet_root: str, records: list[PublicDayRecord], do_push: bool,
) -> None:
    """Spec § 7 git 連携: status check → pull rebase → regen → stage one file → commit → push."""
    log_path = repo_path / diet_root / "log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # pull --rebase (リモートあれば)。do_push=False で skip
    if do_push:
        subprocess.run(["git", "pull", "--rebase"], cwd=repo_path, check=True)

    # 既存 log.json を読んで validate (段 1)
    existing = None
    if log_path.exists():
        existing = json.loads(log_path.read_text(encoding="utf-8"))

    final = build_log_json(records, existing)
    log_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    rel = str(log_path.relative_to(repo_path)).replace("\\", "/")
    subprocess.run(["git", "add", rel], cwd=repo_path, check=True)
    dates = ", ".join(r.date.isoformat() for r in records)
    subprocess.run(["git", "commit", "-m", f"diet: {dates} update"], cwd=repo_path, check=True)
    if do_push:
        subprocess.run(["git", "push"], cwd=repo_path, check=True)
```

```bash
uv run pytest tests/test_publish_git.py -v
git add src/diet/publish.py tests/test_publish_git.py
git commit -m "feat(publish): git operations wrapper (status -> pull -> stage one -> commit -> push)"
```

---

## Phase 6: CLI コマンド

### Task 6.1: cli.py — diet init コマンド

**Files:**
- Modify: `src/diet/cli.py`
- Modify: `src/diet/oauth.py` (high-level run_init_flow を追加)
- Create: `tests/test_cli_init.py`

- [ ] **Step 1: テスト**

```python
from click.testing import CliRunner
from diet.cli import app

def test_init_creates_db_and_config(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    # OAuth フローを mock
    mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["init"], input="1979-12-01\n169\nmale\n\n\n\n2000\n")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "diet.db").exists()
```

(mocker fixture には `pytest-mock` を pyproject の dev deps に追加。)

- [ ] **Step 2: 失敗確認 → 実装 → パス → Commit**

`src/diet/cli.py`:
```python
import os
from pathlib import Path
import click
from diet.db import open_db, save_config, Config
from datetime import date

@click.group()
def app() -> None:
    """Personal diet tracking CLI."""

def _data_dir() -> Path:
    return Path(os.environ.get("DIET_DATA_DIR", "data"))

@app.command()
@click.option("--port", default=8765, type=int)
def init(port: int) -> None:
    """First-time setup: profile, OAuth, initial sync."""
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    birthday = click.prompt("生年月日 (YYYY-MM-DD)", type=click.DateTime(formats=["%Y-%m-%d"]))
    height = click.prompt("身長 (cm)", type=int)
    sex = click.prompt("性別 (male/female)", type=click.Choice(["male", "female"]))
    tz = click.prompt("タイムゾーン", default="Asia/Tokyo")
    hpath = click.prompt("HPasaneel リポジトリパス", default="C:/code/HPasaneel")
    droot = click.prompt("HPasaneel ダッシュボードルート", default="content/diet")
    bootstrap = click.prompt("普段 1 日に食べているカロリー目安 (不明なら Enter)", default="", show_default=False)
    bootstrap_val = int(bootstrap) if bootstrap.strip() else None

    cfg = Config(birthday=birthday.date(), height_cm=height, sex=sex, timezone=tz,
                 hpasaneel_path=hpath, hpasaneel_diet_root=droot,
                 exercise_calorie_source=None, bootstrap_daily_kcal=bootstrap_val)
    conn = open_db(data_dir / "diet.db")
    save_config(conn, cfg)
    click.echo("config saved.")

    # 自己署名証明書 + OAuth フロー
    from diet.oauth import run_init_flow
    run_init_flow(data_dir=data_dir, port=port, conn=conn)
    click.echo("初期セットアップ完了。`diet calibrate` で exercise_kcal の値を決めてください。")
```

`src/diet/oauth.py` に追記:
```python
def run_init_flow(data_dir: Path, port: int, conn) -> None:
    """High-level wrapper: generate cert, build URL, open browser, run callback, save token."""
    import webbrowser, secrets, os, asyncio
    from diet.db import save_token_atomic
    cert = data_dir / "oauth_cert.pem"
    key = data_dir / "oauth_key.pem"
    generate_self_signed_cert(cert, key, "localhost", 3650)
    client_id = os.environ["FITBIT_CLIENT_ID"]
    client_secret = os.environ["FITBIT_CLIENT_SECRET"]
    redirect = f"https://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)
    url = build_authorization_url(client_id, redirect, ["activity", "weight"], state)
    print(f"ブラウザを開いて以下の URL にアクセスしてください:\n{url}")
    print("（初回は証明書警告 → Advanced → Proceed to localhost (unsafe)）")
    webbrowser.open(url)
    cb = run_callback_server(cert, key, port=port)
    if cb.error or not cb.code or cb.state != state:
        raise click.ClickException(f"OAuth failed: error={cb.error}, state mismatch?")
    tok = asyncio.run(exchange_code_for_token(client_id, client_secret, cb.code, redirect))
    save_token_atomic(conn, tok)
    print("Fitbit OAuth 成功、token 保存完了。")
```

```bash
uv run pytest tests/test_cli_init.py -v
git add src/diet/cli.py src/diet/oauth.py tests/test_cli_init.py pyproject.toml
git commit -m "feat(cli): diet init command with OAuth flow"
```

---

### Task 6.2: cli.py — diet sync コマンド

**Files:**
- Modify: `src/diet/cli.py`
- Modify: `src/diet/fitbit_client.py`
- Create: `tests/test_cli_sync.py`

- [ ] **Step 1〜5: TDD サイクル**

`diet sync` は config + token を読んで `FitbitClient` 経由で過去 30 日（init 時）or 直近 N 日（通常時）の activity と weight を取得、DB に upsert。

(詳細は省略しますが、構造は Task 6.1 と同形式: テスト書く → fail → 実装 → pass → commit)

実装の骨子:
```python
@app.command()
@click.option("--days", default=7, type=int, help="how many past days to sync")
def sync(days: int) -> None:
    conn = open_db(_data_dir() / "diet.db")
    tok = load_token(conn)
    if tok is None:
        raise click.ClickException("Not authenticated. Run `diet init` first.")
    async def refresh_cb():
        from diet.db import save_token_atomic
        new_tok = await refresh_access_token(os.environ["FITBIT_CLIENT_ID"],
                                              os.environ["FITBIT_CLIENT_SECRET"],
                                              tok.refresh_token)
        save_token_atomic(conn, new_tok)
        return new_tok.access_token
    client = FitbitClient(tok.access_token, on_unauthorized=refresh_cb)
    asyncio.run(_run_sync(client, conn, days))
```

```bash
git commit -m "feat(cli): diet sync fetches Fitbit activity + weight"
```

---

### Task 6.3: cli.py — diet, calibrate, weight, baseline, show, auth

各コマンド独立、それぞれ TDD で 1 タスクずつ:
- **diet** (引数なしのデフォルトコマンド) → orchestrator.run_daily_flow を呼ぶ (Task 7)
- **calibrate** → 過去 N 日の logged_activities_kcal / marginal_kcal を表で表示、ユーザー入力で config 更新
- **weight 71.2** → daily_weight に upsert (`--date` オプション可)
- **baseline 2200** → config.bootstrap_daily_kcal 更新
- **show** → 指定日の収支のみ表示（食事入力・publish なし、orchestrator のサブセット呼び出し）
- **auth** → run_init_flow の OAuth 部分だけ再実行

各コマンド 1 commit:
```bash
git commit -m "feat(cli): diet calibrate command"
git commit -m "feat(cli): diet weight manual entry"
git commit -m "feat(cli): diet baseline command"
git commit -m "feat(cli): diet show display-only mode"
git commit -m "feat(cli): diet auth re-authentication"
```

---

## Phase 7: orchestrator + formatters

### Task 7.1: orchestrator.py — 5 ステップ対話フロー

**Files:**
- Create: `src/diet/orchestrator.py`
- Create: `src/diet/formatters.py`
- Create: `tests/test_orchestrator_e2e.py`

- [ ] **Step 1: テスト (E2E、外部 I/O は全部 mock)**

```python
def test_orchestrator_full_flow_with_recorded_authoritative(tmp_path, monkeypatch, mocker):
    # config + token + history を仕込んだ DB を作る
    # FitbitClient を mock して固定 activity を返させる
    # click.prompt をパッチして食事入力 =1800 を返させる
    # publish_to_hpasaneel を mock してファイル書き出し回数を検証
    # 出力 lines を assert
    ...
```

(詳細は実装時に肉付け。テストは `pytest -v` で挙動を観察しながら書く)

- [ ] **Step 2〜4**: 失敗確認 → 実装 → パス

`src/diet/orchestrator.py` の骨子:
```python
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import click
from diet.db import (open_db, load_config, load_token, save_token_atomic,
                     get_events_for_date, get_events_in_range, insert_intake_event,
                     get_daily_activity, get_latest_weight_on_or_before)
from diet.bmr import age_at, mifflin_st_jeor
from diet.intake import past_avg, decide_intake_kcal
from diet.publish import publish_to_hpasaneel, PublicDayRecord
from diet.formatters import format_intake_display, format_balance

def run_daily_flow(data_dir, target_date: date | None = None, do_publish_prompt: bool = True):
    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    tz = ZoneInfo(cfg.timezone)
    today = target_date or datetime.now(tz).date()

    # [1] Fitbit sync (target_date を含む直近 7 日)
    _run_sync(conn, today, days=7)

    # [2] 食事入力
    cur_events = get_events_for_date(conn, today)
    cur_sum = sum(e.kcal for e in cur_events) if cur_events else 0
    user_in = click.prompt(f"今日のカロリー (現在の累積: {cur_sum}kcal) [+追加/=上書き/Enter=skip]",
                           default="", show_default=False)
    _handle_intake_input(conn, today, user_in)

    # [3] BMR
    weight = get_latest_weight_on_or_before(conn, today)
    age = age_at(cfg.birthday, today)
    bmr = mifflin_st_jeor(weight_kg=weight.weight_kg, height_cm=cfg.height_cm, age=age, sex=cfg.sex)

    # [4] 収支
    history = get_events_in_range(conn, today - timedelta(days=14), today)
    avg, n = past_avg(history, today)
    today_events = get_events_for_date(conn, today)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    activity = get_daily_activity(conn, today)
    exercise_kcal = _resolve_exercise_kcal(activity, cfg.exercise_calorie_source)
    click.echo(format_intake_display(decision))
    click.echo(format_balance(decision.intake_kcal, bmr, exercise_kcal, activity, weight))

    # [5] publish
    if do_publish_prompt and click.confirm("HPasaneel に運動・体重のみ公開しますか?"):
        record = PublicDayRecord(date=today, steps=activity.steps, distance_km=activity.distance_km,
                                  exercise_kcal=exercise_kcal, weight_kg=weight.weight_kg)
        publish_to_hpasaneel(Path(cfg.hpasaneel_path), cfg.hpasaneel_diet_root, [record], do_push=True)
```

- [ ] **Step 5: Commit**

```bash
git add src/diet/orchestrator.py src/diet/formatters.py tests/test_orchestrator_e2e.py
git commit -m "feat(orchestrator): 5-step daily flow with formatter integration"
```

---

### Task 7.2: formatters.py — 各 label の表示文字列

**Files:**
- Modify: `src/diet/formatters.py`
- Create: `tests/test_formatters.py`

- [ ] **Step 1〜5: TDD**

7 ケースのラベル (`recorded_authoritative` 〜 `unconfirmed`) それぞれに対応する日本語表示文字列を返す純粋関数を実装。

```python
def format_intake_display(d: IntakeDecision) -> str:
    if d.label == "recorded_authoritative":
        return f"摂取 {d.intake_kcal:,} kcal (記録)"
    if d.label == "recorded_partial_high":
        return f"摂取 {d.intake_kcal:,} kcal (部分入力、過去平均超え)"
    if d.label == "estimated_avg_supplement":
        return f"摂取 推定 {d.intake_kcal:,} kcal (記録 {d.recorded_part:,} + 平均補完 {d.supplement_part:,}、N={d.n_samples})"
    ...
```

```bash
git commit -m "feat(formatters): localized display strings for all 7 intake labels"
```

---

## Phase 8: HPasaneel ダッシュボード

### Task 8.1: HPasaneel — recharts 依存追加 + content/diet 初期 commit

**Files:**
- Modify: `C:/code/HPasaneel/package.json`
- Create: `C:/code/HPasaneel/content/diet/log.json` (空 doc)
- Modify: `C:/code/HPasaneel/.gitignore` (もし `content/` 全部除外してたら `!content/diet/log.json` で例外)

- [ ] **Step 1〜3**:

```bash
cd C:/code/HPasaneel
npm install recharts
```

`content/diet/log.json` の初期内容:
```json
{
  "updated_at": "2026-05-25T00:00:00+09:00",
  "days": []
}
```

```bash
cd C:/code/HPasaneel
git add package.json package-lock.json content/diet/log.json
git commit -m "feat(diet): add recharts dependency + empty log.json placeholder"
```

---

### Task 8.2: HPasaneel — app/diet/page.tsx ダッシュボード

**Files:**
- Create: `C:/code/HPasaneel/app/diet/page.tsx`

- [ ] **Step 1: テスト（手動で `npm run dev` 後に http://localhost:3000/diet を目視確認）**

- [ ] **Step 2: 実装**

`app/diet/page.tsx`:
```tsx
import log from "../../content/diet/log.json";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface DayRecord {
  date: string;
  steps: number;
  distance_km: number;
  exercise_kcal: number;
  weight_kg: number;
}

export default function DietPage() {
  const days = (log.days as DayRecord[]).slice().reverse(); // 古い順
  const latest = log.days[0];
  return (
    <main className="prose mx-auto p-8">
      <h1>Diet Dashboard</h1>
      <p>最終更新: {log.updated_at}</p>
      <h2>体重推移</h2>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={days}>
          <XAxis dataKey="date" />
          <YAxis domain={["dataMin - 1", "dataMax + 1"]} />
          <Tooltip />
          <Line type="monotone" dataKey="weight_kg" stroke="#8884d8" />
        </LineChart>
      </ResponsiveContainer>
      <h2>歩数</h2>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={days}>
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="steps" fill="#82ca9d" />
        </BarChart>
      </ResponsiveContainer>
      <h2>運動消費 kcal</h2>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={days}>
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="exercise_kcal" fill="#ffc658" />
        </BarChart>
      </ResponsiveContainer>
    </main>
  );
}
```

- [ ] **Step 3: 動作確認**

```bash
cd C:/code/HPasaneel
npm run dev
# ブラウザで http://localhost:3000/diet
```

- [ ] **Step 4: Commit**

```bash
git add app/diet/page.tsx
git commit -m "feat(diet): dashboard page with weight/steps/calorie charts"
```

---

### Task 8.3: HPasaneel — メインナビに Diet 追加

**Files:**
- Modify: `C:/code/HPasaneel/app/layout.tsx`

- [ ] **Step 1: 既存 layout.tsx を Read で確認**

- [ ] **Step 2: ナビ配列に `{ href: "/diet", label: "Diet" }` を追加**

- [ ] **Step 3: `npm run dev` で動作確認**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(diet): add Diet link to main navigation"
```

---

## Phase 9: 仕上げ

### Task 9.1: README

**Files:**
- Create: `C:/code/fitbit連動ダイエット/README.md`

- [ ] **Step 1: 内容**

セットアップ手順、Fitbit dev portal 登録（spec § 8.1 の表を流用）、Renpho → Fitbit 連携、`uv tool install .`、初回 `diet init` の流れ、各 CLI コマンド一覧（spec § 9 流用）。

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup and command reference"
```

---

### Task 9.2: E2E スモーク（手動チェック）

- [ ] **Step 1**: Fitbit dev portal で実アプリ登録 (spec § 8.1 の表に従う)
- [ ] **Step 2**: `.env` に Client ID/Secret 記入
- [ ] **Step 3**: `uv tool install .` で diet コマンドを global に入れる
- [ ] **Step 4**: `diet init` を実行、生年月日 1979-12-01 / 169 / male / Asia/Tokyo / C:/code/HPasaneel / content/diet / 2000 と入力、ブラウザで Fitbit 認証完了
- [ ] **Step 5**: `diet calibrate` で exercise_calorie_source を `marginal` に確定
- [ ] **Step 6**: `diet` を実行、`=2300` で食事入力、収支表示確認、`y` で publish
- [ ] **Step 7**: HPasaneel リポジトリで `git log` 確認、cloudflare deploy 待ち、`/diet` ページで data 表示確認

---

## Plan Review Loop

After this plan is reviewed by spec-document-reviewer / plan-document-reviewer:
- If issues: fix and re-dispatch
- If approved: proceed to subagent-driven-development

---

## Execution Handoff (planned)

Per user global rule: subagent-driven (option 1) is the default. After plan approval:
- Use `superpowers:subagent-driven-development` skill
- Fresh subagent per task, two-stage review between tasks
- ~30 tasks expected, ~3-5 commits per task = comprehensive history
