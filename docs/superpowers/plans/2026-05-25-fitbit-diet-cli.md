# Fitbit 連動ダイエット CLI 実装計画 (rev 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fitbit API・Renpho 体重・手動食事入力を統合し、収支算出と HPasaneel ダッシュ公開を 1 つの対話型 CLI コマンド `diet` で完結させる。

**Architecture:** Python + uv 単一 CLI、SQLite ストレージ、Fitbit OAuth 2.0 (HTTPS localhost callback + 自己署名証明書)、純粋関数ファースト設計で TDD 高被覆。公開境界は 2 層 allowlist（DTO + JSON schema）で `note` 漏洩を構造的に防止。HPasaneel 側は Next.js App Router 上に recharts ダッシュページを 1 つ追加（client component）。

**Tech Stack:** Python 3.11+, uv, httpx, click, jsonschema, cryptography, pytest, pytest-httpx, pytest-asyncio, pytest-mock, freezegun; HPasaneel: Next.js 15 (App Router) + recharts。

**Source spec:** `docs/superpowers/specs/2026-05-25-fitbit-diet-design.md` (rev 9)。実装中の不明点はすべて spec を一次ソースとして参照。

**Reference skills:**
- @superpowers:test-driven-development — 全タスクが Red → Green → Refactor の TDD で進行
- @superpowers:systematic-debugging — テストが想定外に通った／落ちた時はこちらへ

**Plan version history:**
- rev 1 (a04a630) → codex GO-WITH-FIXES、placeholder/granularity/edge case 不足
- rev 2 → 全 CLI コマンドを TDD タスクに展開、§11 各エッジケースに個別タスク、Phase 8 "use client" 対応、boundary test 強化
- rev 3 → codex rev2 review 反映: 2-stage validate の独立 reject test、SQL trace_callback、Phase 9 全テストを具体化、cur_sum を recorded_sum 経由、page.tsx vs DietCharts.tsx の役割明確化

---

## File Structure

### Python パッケージ (`C:/code/fitbit連動ダイエット/`)

```
pyproject.toml                    # uv 管理、entry point: diet = "diet.cli:app"
.env.example                      # FITBIT_CLIENT_ID/SECRET/REDIRECT_URI 雛形
.gitignore                        # data/, .env, *.pem 追加
README.md                         # セットアップ手順

src/diet/
  __init__.py                     # __version__
  __main__.py                     # python -m diet エントリ
  cli.py                          # click 定義、全コマンド
  orchestrator.py                 # diet コマンド本体の 5 ステップ対話フロー
  bmr.py                          # 純粋関数: age_at, mifflin_st_jeor
  intake.py                       # 純粋関数: recorded_sum, is_complete_day, past_avg, decide_intake_kcal
  db.py                           # SQLite 接続・スキーマ・migration、各テーブル CRUD
  oauth.py                        # 自己署名証明書、HTTPS callback サーバー、token 交換、atomic rotation
  fitbit_client.py                # httpx ラッパー、token 自動 refresh、rate limit 追跡
  publish.py                      # PublicDayRecord DTO、JSON schema、merge、git 操作
  calibrate.py                    # diet calibrate コマンド本体
  formatters.py                   # CLI 表示文字列生成
  helpers.py                      # _resolve_exercise_kcal 等の内部関数

tests/
  conftest.py                     # 共通 fixtures (tmp_db, sample_events, mock_fitbit)
  test_bmr.py
  test_intake.py
  test_intake_regression.py
  test_db.py
  test_oauth.py
  test_fitbit_client.py
  test_fitbit_client_rate_limit.py
  test_publish_boundary.py        # ★note "ラーメン特盛" 等が log.json に絶対出ない
  test_publish_schema.py          # 2 段 validate の両段が独立に reject すること
  test_publish_merge.py           # 既存日 entry の保持、対象日のみ差し替え
  test_publish_git.py             # subprocess git ops
  test_cli_init.py
  test_cli_sync.py
  test_cli_calibrate.py
  test_cli_weight.py
  test_cli_baseline.py
  test_cli_show.py
  test_cli_auth.py
  test_cli_default.py             # 引数なし `diet` がデフォルト対話フローを起動
  test_orchestrator_e2e.py
  test_formatters.py
  test_edgecases.py               # §11 エッジケース統合
```

### HPasaneel 側 (`C:/code/HPasaneel/`)

```
app/diet/page.tsx                 # server component。log.json を import → props で client に渡す
app/diet/DietCharts.tsx           # ★ "use client" — recharts を含む実描画はこちら
app/layout.tsx                    # メインナビに "Diet" 追加（既存編集）
content/diet/log.json             # diet コマンドが書き出す（commit 対象）
package.json                      # recharts 依存追加
```

---

# Phase 0: Scaffold

## Task 0.1: プロジェクト scaffold + uv 初期化

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `src/diet/__init__.py`, `src/diet/__main__.py`, `src/diet/cli.py`
- Create: `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: pyproject.toml 作成**

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
  "pytest-asyncio>=0.23",
  "pytest-mock>=3.12",
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
asyncio_mode = "auto"
```

- [ ] **Step 2: .env.example**

```
FITBIT_CLIENT_ID=
FITBIT_CLIENT_SECRET=
FITBIT_REDIRECT_URI=https://localhost:8765/callback
```

- [ ] **Step 3: .gitignore 追記**

既存 .gitignore の末尾に:
```
# fitbit-diet specific
data/
.env
*.pem
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: ソース構造作成**

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

@click.group(invoke_without_command=True)
@click.pass_context
def app(ctx: click.Context) -> None:
    """Personal diet tracking CLI."""
    if ctx.invoked_subcommand is None:
        # 引数なし: デフォルト対話フローへ (Task 6.8 で本実装)
        click.echo("orchestrator not yet implemented")
```

`tests/__init__.py`: 空。

`tests/conftest.py`:
```python
import pytest
from pathlib import Path

@pytest.fixture
def tmp_db(tmp_path: Path):
    from diet.db import open_db
    return open_db(tmp_path / "test.db")
```

- [ ] **Step 5: smoke**

```bash
uv sync
uv run python -c "import diet; print(diet.__version__)"
uv run diet --help
```
Expected: `0.1.0` と click help。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example .gitignore src/ tests/
git commit -m "feat: project scaffold (uv + click + pytest)"
```

---

# Phase 1: 純粋関数 (bmr, intake)

## Task 1.1: bmr.py — age_at

**Files:** Create `src/diet/bmr.py`, `tests/test_bmr.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_bmr.py
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

- [ ] **Step 2: Run, verify failure**

`uv run pytest tests/test_bmr.py -v` → ImportError。

- [ ] **Step 3: Minimal implementation**

```python
# src/diet/bmr.py
from datetime import date

def age_at(birthday: date, target_date: date) -> int:
    age = target_date.year - birthday.year
    if (target_date.month, target_date.day) < (birthday.month, birthday.day):
        age -= 1
    return age
```

- [ ] **Step 4: Run, verify pass**

`uv run pytest tests/test_bmr.py -v` → 6 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/bmr.py tests/test_bmr.py
git commit -m "feat(bmr): age_at handles birthday boundary"
```

## Task 1.2: bmr.py — Mifflin-St Jeor

**Files:** Modify `src/diet/bmr.py`, `tests/test_bmr.py`

- [ ] **Step 1: Add failing tests**

```python
# Append to tests/test_bmr.py
import pytest
from diet.bmr import mifflin_st_jeor

def test_bmr_male_70kg_46y_169cm():
    # 700 + 1056.25 - 230 + 5 = 1531.25
    assert mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male") == 1531.25

def test_bmr_height_169_constant_unfolded():
    """Regression: 6.25 * 169 = 1056.25 (NOT 836.25)."""
    assert mifflin_st_jeor(weight_kg=0.0, height_cm=169, age=0, sex="male") == 1061.25

def test_bmr_female_offset():
    male = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male")
    female = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="female")
    assert female == male - 5 + (-161)  # male offset +5 vs female -161

def test_bmr_invalid_sex_raises():
    with pytest.raises(ValueError):
        mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="other")
```

- [ ] **Step 2: Verify fail**: `uv run pytest tests/test_bmr.py -v` → ImportError。

- [ ] **Step 3: Implement**

```python
# Append to src/diet/bmr.py
def mifflin_st_jeor(weight_kg: float, height_cm: int, age: int, sex: str) -> float:
    if sex == "male":
        offset = 5
    elif sex == "female":
        offset = -161
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + offset
```

- [ ] **Step 4: Verify pass**: `uv run pytest tests/test_bmr.py -v` → 全 passed。

- [ ] **Step 5: Commit**

```bash
git add src/diet/bmr.py tests/test_bmr.py
git commit -m "feat(bmr): Mifflin-St Jeor formula with explicit constants"
```

---

## Task 1.3: intake.py — recorded_sum + op semantics + deterministic order

**Files:** Create `src/diet/intake.py`, `tests/test_intake.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_intake.py
from datetime import datetime
from diet.intake import IntakeEvent, recorded_sum

def E(kcal, op, ts="2026-05-25T12:00:00", id=0):
    return IntakeEvent(id=id, timestamp=datetime.fromisoformat(ts), kcal=kcal, op=op)

def test_recorded_sum_empty():
    assert recorded_sum([]) is None

def test_recorded_sum_append_only():
    assert recorded_sum([E(500, "append"), E(300, "append")]) == 800

def test_recorded_sum_override_only():
    assert recorded_sum([E(2000, "override")]) == 2000

def test_recorded_sum_override_then_append():
    events = [
        E(500, "append"),
        E(2000, "override", ts="2026-05-25T13:00:00"),
        E(200, "append", ts="2026-05-25T14:00:00"),
    ]
    assert recorded_sum(events) == 2200

def test_recorded_sum_multiple_overrides_last_wins():
    events = [
        E(2000, "override", ts="2026-05-25T12:00:00"),
        E(1500, "override", ts="2026-05-25T13:00:00"),
    ]
    assert recorded_sum(events) == 1500

def test_recorded_sum_zero_fasting():
    assert recorded_sum([E(0, "override")]) == 0

def test_recorded_sum_same_ts_id_asc_tiebreak():
    ts = "2026-05-25T12:00:00"
    events = [E(2000, "override", ts=ts, id=2), E(1500, "override", ts=ts, id=1)]
    # id 1 -> 2 の順 → 後の id=2 (2000) が勝つ
    assert recorded_sum(events) == 2000
```

- [ ] **Step 2: Verify fail**: ImportError。

- [ ] **Step 3: Implement**

```python
# src/diet/intake.py
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class IntakeEvent:
    id: int
    timestamp: datetime
    kcal: int
    op: str  # 'append' | 'override'

def recorded_sum(events: list[IntakeEvent]) -> int | None:
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
    after = sum(e.kcal for e in sorted_events[last_override_idx + 1:] if e.op == "append")
    return baseline + after
```

- [ ] **Step 4: Verify pass**: 全 passed。

- [ ] **Step 5: Commit**: `git commit -m "feat(intake): recorded_sum with op semantics + deterministic ordering"`

---

## Task 1.4: intake.py — is_complete_day

**Files:** Modify `src/diet/intake.py`, `tests/test_intake.py`

- [ ] **Step 1: Add failing tests**

```python
from diet.intake import is_complete_day

def test_complete_with_override():
    assert is_complete_day([E(2000, "override")]) is True

def test_complete_append_only_false():
    assert is_complete_day([E(500, "append")]) is False

def test_complete_empty_false():
    assert is_complete_day([]) is False

def test_complete_mixed_with_override_true():
    assert is_complete_day([E(500, "append"), E(2000, "override")]) is True
```

- [ ] **Step 2-3: Implement**

```python
def is_complete_day(events: list[IntakeEvent]) -> bool:
    return any(e.op == "override" for e in events)
```

- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit**: `git commit -m "feat(intake): is_complete_day"`

---

## Task 1.5: intake.py — past_avg + sample floor + half-open window

**Files:** Modify `src/diet/intake.py`, `tests/test_intake.py`

- [ ] **Step 1: Failing tests** (Task 1.5 in rev1 plan、全 8 ケース、半開区間境界含む)

```python
from datetime import date, datetime, timedelta
from diet.intake import past_avg, DailyEvents, SAMPLE_FLOOR

def D(events):
    return DailyEvents(events=events)

def Ed(kcal, op, day):
    return IntakeEvent(id=0, timestamp=datetime(day.year, day.month, day.day, 12, 0), kcal=kcal, op=op)

def test_sample_floor_is_three():
    assert SAMPLE_FLOOR == 3

def test_past_avg_empty_history():
    assert past_avg({}, target_date=date(2026, 5, 25)) == (None, 0)

def test_past_avg_below_floor_returns_none():
    history = {
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg is None
    assert n == 2

def test_past_avg_at_floor():
    history = {
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
        date(2026, 5, 22): D([Ed(2200, "override", date(2026, 5, 22))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3

def test_past_avg_excludes_partial_days():
    history = {
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
        date(2026, 5, 22): D([Ed(2200, "override", date(2026, 5, 22))]),
        date(2026, 5, 21): D([Ed(500, "append", date(2026, 5, 21))]),
        date(2026, 5, 20): D([Ed(300, "append", date(2026, 5, 20))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3

def test_past_avg_half_open_excludes_target_date():
    history = {
        date(2026, 5, 25): D([Ed(9999, "override", date(2026, 5, 25))]),
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
        date(2026, 5, 22): D([Ed(2200, "override", date(2026, 5, 22))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert n == 3

def test_past_avg_includes_target_minus_14():
    target = date(2026, 5, 25)
    history = {
        target - timedelta(days=14): D([Ed(2000, "override", target - timedelta(days=14))]),
        target - timedelta(days=13): D([Ed(1800, "override", target - timedelta(days=13))]),
        target - timedelta(days=12): D([Ed(2200, "override", target - timedelta(days=12))]),
    }
    avg, n = past_avg(history, target_date=target)
    assert n == 3
    assert avg == 2000.0

def test_past_avg_excludes_target_minus_15():
    target = date(2026, 5, 25)
    history = {
        target - timedelta(days=15): D([Ed(9999, "override", target - timedelta(days=15))]),
        target - timedelta(days=14): D([Ed(2000, "override", target - timedelta(days=14))]),
        target - timedelta(days=13): D([Ed(1800, "override", target - timedelta(days=13))]),
        target - timedelta(days=12): D([Ed(2200, "override", target - timedelta(days=12))]),
    }
    avg, n = past_avg(history, target_date=target)
    assert n == 3
    assert avg == 2000.0
```

- [ ] **Step 2-3: Implement**

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
    """Half-open window [target_date - 14, target_date), complete days only."""
    start = target_date - timedelta(days=14)
    sums: list[int] = []
    for d, daily in history.items():
        if start <= d < target_date and is_complete_day(daily.events):
            s = recorded_sum(daily.events)
            if s is not None:
                sums.append(s)
    n = len(sums)
    if n < SAMPLE_FLOOR:
        return (None, n)
    return (sum(sums) / n, n)
```

- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit**: `git commit -m "feat(intake): past_avg with sample floor + half-open window"`

---

## Task 1.6: intake.py — decide_intake_kcal (7-case decision)

**Files:** Modify `src/diet/intake.py`, `tests/test_intake.py`

- [ ] **Step 1: Failing tests (7 cases + =0 regression)**

```python
from diet.intake import decide_intake_kcal, IntakeDecision

def test_case1_complete_recorded_authoritative():
    d = decide_intake_kcal([E(1800, "override")], past_avg_val=2000.0, n_samples=10, bootstrap_baseline=2200)
    assert d.intake_kcal == 1800
    assert d.label == "recorded_authoritative"

def test_case1_fasting_zero_not_inflated():
    """★最重要: =0 が past_avg・baseline で水増しされない"""
    d = decide_intake_kcal([E(0, "override")], past_avg_val=2200.0, n_samples=10, bootstrap_baseline=2000)
    assert d.intake_kcal == 0
    assert d.label == "recorded_authoritative"

def test_case2_partial_recorded_high_with_avg():
    d = decide_intake_kcal([E(2400, "append")], past_avg_val=2000.0, n_samples=10, bootstrap_baseline=None)
    assert d.intake_kcal == 2400
    assert d.label == "recorded_partial_high"

def test_case2_partial_recorded_low_with_avg():
    d = decide_intake_kcal([E(500, "append")], past_avg_val=2100.0, n_samples=11, bootstrap_baseline=None)
    assert d.intake_kcal == 2100
    assert d.label == "estimated_avg_supplement"
    assert d.recorded_part == 500
    assert d.supplement_part == 1600

def test_case3_partial_no_avg_baseline_supplemented():
    d = decide_intake_kcal([E(500, "append")], past_avg_val=None, n_samples=2, bootstrap_baseline=2000)
    assert d.intake_kcal == 2000
    assert d.label == "estimated_baseline_supplement"

def test_case4_partial_no_avg_no_baseline():
    d = decide_intake_kcal([E(500, "append")], past_avg_val=None, n_samples=0, bootstrap_baseline=None)
    assert d.intake_kcal == 500
    assert d.label == "recorded_no_baseline"

def test_case5_empty_avg_available():
    d = decide_intake_kcal([], past_avg_val=1980.0, n_samples=8, bootstrap_baseline=2000)
    assert d.intake_kcal == 1980
    assert d.label == "estimated_avg"

def test_case6_empty_no_avg_baseline_used():
    d = decide_intake_kcal([], past_avg_val=None, n_samples=2, bootstrap_baseline=2000)
    assert d.intake_kcal == 2000
    assert d.label == "estimated_baseline"

def test_case7_empty_no_avg_no_baseline():
    d = decide_intake_kcal([], past_avg_val=None, n_samples=0, bootstrap_baseline=None)
    assert d.intake_kcal is None
    assert d.label == "unconfirmed"
```

- [ ] **Step 2-3: Implement**

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
    rec = recorded_sum(today_events)
    is_complete = is_complete_day(today_events)
    has_avg = past_avg_val is not None
    has_baseline = bootstrap_baseline is not None

    if is_complete:
        return IntakeDecision(intake_kcal=rec, label="recorded_authoritative", n_samples=n_samples)

    if rec is not None:
        if has_avg:
            if rec >= past_avg_val:
                return IntakeDecision(intake_kcal=rec, label="recorded_partial_high", n_samples=n_samples)
            est = round(past_avg_val)
            return IntakeDecision(intake_kcal=est, label="estimated_avg_supplement",
                                   recorded_part=rec, supplement_part=est - rec, n_samples=n_samples)
        if has_baseline:
            est = max(rec, bootstrap_baseline)
            return IntakeDecision(intake_kcal=est, label="estimated_baseline_supplement",
                                   recorded_part=rec, supplement_part=est - rec, n_samples=n_samples)
        return IntakeDecision(intake_kcal=rec, label="recorded_no_baseline", n_samples=n_samples)

    if has_avg:
        return IntakeDecision(intake_kcal=round(past_avg_val), label="estimated_avg", n_samples=n_samples)
    if has_baseline:
        return IntakeDecision(intake_kcal=bootstrap_baseline, label="estimated_baseline", n_samples=n_samples)
    return IntakeDecision(intake_kcal=None, label="unconfirmed", n_samples=n_samples)
```

- [ ] **Step 4-5: Pass, Commit**: `git commit -m "feat(intake): 7-case decision with fasting-day protection"`

---

## Task 1.7: intake.py — TDD regression test for fasting day (Red first)

**Files:** Create `tests/test_intake_regression.py`

注: Task 1.6 が pass する **前に** Task 1.7 のテストを書くのが理想だが、Task 1.7 は統合シナリオなので 1.6 の後でも構わない。ただし test ファイルを別にすることで「絶対壊さない」回帰テスト群として明確化する。

- [ ] **Step 1: Test**

```python
from datetime import date, datetime
from diet.intake import IntakeEvent, DailyEvents, past_avg, decide_intake_kcal

def Ed(kcal, op, d):
    return IntakeEvent(id=0, timestamp=datetime(d.year, d.month, d.day, 12, 0), kcal=kcal, op=op)

def test_fasting_after_normal_history():
    """過去 14 日 平均 2200 → 今日 =0 → 0 のまま"""
    history = {
        date(2026, 5, 25) - __import__("datetime").timedelta(days=i): DailyEvents(events=[
            Ed(2200, "override", date(2026, 5, 25) - __import__("datetime").timedelta(days=i))
        ]) for i in range(1, 15)
    }
    target = date(2026, 5, 25)
    today = [Ed(0, "override", target)]
    avg, n = past_avg(history, target)
    assert avg == 2200.0 and n == 14
    d = decide_intake_kcal(today, avg, n, bootstrap_baseline=2000)
    assert d.intake_kcal == 0

def test_restriction_day_stays_low():
    """=1200 制限日が 2200 平均で水増しされない"""
    history = {
        date(2026, 5, 25) - __import__("datetime").timedelta(days=i): DailyEvents(events=[
            Ed(2200, "override", date(2026, 5, 25) - __import__("datetime").timedelta(days=i))
        ]) for i in range(1, 15)
    }
    target = date(2026, 5, 25)
    today = [Ed(1200, "override", target)]
    avg, n = past_avg(history, target)
    d = decide_intake_kcal(today, avg, n, bootstrap_baseline=2000)
    assert d.intake_kcal == 1200
```

- [ ] **Step 2: Verify pass (実装は 1.6 で完了済み)**: passed。

- [ ] **Step 3: Commit**: `git commit -m "test(intake): regression suite for fasting/restriction days"`

---

# Phase 2: ストレージ (db.py)

## Task 2.1: db.py — スキーマ migration + 単一行制約

**Files:** Create `src/diet/db.py`, `tests/test_db.py`

- [ ] **Step 1: Failing tests**

```python
import sqlite3
import pytest
from pathlib import Path
from diet.db import open_db

def test_creates_all_tables(tmp_path):
    conn = open_db(tmp_path / "t.db")
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    expected = {"config", "intake_events", "daily_activity", "daily_weight", "fitbit_token", "_meta"}
    assert expected.issubset(names)

def test_idempotent(tmp_path):
    p = tmp_path / "t.db"
    open_db(p).close()
    open_db(p).close()  # 例外なし

def test_config_single_row(tmp_path):
    conn = open_db(tmp_path / "t.db")
    conn.execute("INSERT INTO config (id, birthday, height_cm, sex, timezone) VALUES (1, '1979-12-01', 169, 'male', 'Asia/Tokyo')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO config (id, birthday, height_cm, sex, timezone) VALUES (2, '2000-01-01', 170, 'male', 'Asia/Tokyo')")

def test_fitbit_token_single_row(tmp_path):
    conn = open_db(tmp_path / "t.db")
    conn.execute("INSERT INTO fitbit_token (id, access_token, refresh_token, expires_at, user_id, rotated_at) VALUES (1, 'A', 'R', '2026-12-31', 'U', '2026-01-01')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO fitbit_token (id, access_token, refresh_token, expires_at, user_id, rotated_at) VALUES (2, 'A2', 'R2', '2026-12-31', 'U', '2026-01-01')")
```

- [ ] **Step 2-3: Implement**

`src/diet/db.py`:
```python
import sqlite3
from pathlib import Path

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS _meta (schema_version INTEGER NOT NULL);

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

- [ ] **Step 4-5: Pass, Commit**: `git commit -m "feat(db): schema with single-row constraints"`

---

## Task 2.2: db.py — intake_events CRUD

**Files:** Modify db.py, tests/test_db.py

- [ ] **Step 1: Tests**

```python
from datetime import date, datetime, timedelta
from diet.db import insert_intake_event, get_events_for_date, get_events_in_range
from diet.intake import IntakeEvent

def test_insert_and_get_event(tmp_path):
    conn = open_db(tmp_path / "t.db")
    insert_intake_event(conn, date(2026, 5, 25), datetime(2026, 5, 25, 12, 0), 500, "append", note="ラーメン特盛")
    events = get_events_for_date(conn, date(2026, 5, 25))
    assert len(events) == 1
    assert events[0].kcal == 500
    assert events[0].op == "append"

def test_get_events_in_range_half_open(tmp_path):
    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    for offset in [0, 1, 14, 15]:
        d = target - timedelta(days=offset)
        insert_intake_event(conn, d, datetime(d.year, d.month, d.day, 12, 0), 100 * offset, "override")
    history = get_events_in_range(conn, start=target - timedelta(days=14), end=target)
    keys = sorted(history.keys())
    assert (target - timedelta(days=14)) in history
    assert (target - timedelta(days=15)) not in history
    assert target not in history  # 半開区間 [start, end) で target 排他

def test_get_events_for_date_ordering(tmp_path):
    """同 date 内、timestamp ASC, id ASC で返ること"""
    conn = open_db(tmp_path / "t.db")
    d = date(2026, 5, 25)
    insert_intake_event(conn, d, datetime(2026, 5, 25, 13, 0), 100, "append")
    insert_intake_event(conn, d, datetime(2026, 5, 25, 12, 0), 200, "append")
    events = get_events_for_date(conn, d)
    assert events[0].kcal == 200  # 早い timestamp
    assert events[1].kcal == 100
```

- [ ] **Step 2-3: Implement** (rev1 plan の同タスクと同等)

```python
from dataclasses import dataclass
from datetime import date, datetime
from diet.intake import IntakeEvent, DailyEvents

def _ds(d: date) -> str:
    return d.isoformat()

def insert_intake_event(conn, d, ts, kcal, op, note=None):
    cur = conn.execute(
        "INSERT INTO intake_events (date, timestamp, kcal, op, note) VALUES (?, ?, ?, ?, ?)",
        (_ds(d), ts.isoformat(), kcal, op, note),
    )
    conn.commit()
    return cur.lastrowid

def get_events_for_date(conn, d) -> list[IntakeEvent]:
    rows = conn.execute(
        "SELECT id, timestamp, kcal, op FROM intake_events WHERE date = ? ORDER BY timestamp ASC, id ASC",
        (_ds(d),),
    ).fetchall()
    return [IntakeEvent(id=r[0], timestamp=datetime.fromisoformat(r[1]), kcal=r[2], op=r[3]) for r in rows]

def get_events_in_range(conn, start, end) -> dict[date, DailyEvents]:
    rows = conn.execute(
        "SELECT id, date, timestamp, kcal, op FROM intake_events WHERE date >= ? AND date < ? ORDER BY date, timestamp, id",
        (_ds(start), _ds(end)),
    ).fetchall()
    result: dict[date, list[IntakeEvent]] = {}
    for r in rows:
        d = date.fromisoformat(r[1])
        result.setdefault(d, []).append(IntakeEvent(id=r[0], timestamp=datetime.fromisoformat(r[2]), kcal=r[3], op=r[4]))
    return {d: DailyEvents(events=ev) for d, ev in result.items()}
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(db): intake_events CRUD with half-open range"`

---

## Task 2.3: db.py — daily_activity / daily_weight CRUD + 体重タイムマシン禁止

**Files:** Modify db.py, tests/test_db.py

- [ ] **Step 1: Tests**

```python
from diet.db import upsert_daily_activity, get_daily_activity, upsert_daily_weight, get_latest_weight_on_or_before

def test_daily_activity_upsert(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_daily_activity(conn, date(2026, 5, 25), 8234, 5.3, 280, 340)
    a = get_daily_activity(conn, date(2026, 5, 25))
    assert a.steps == 8234
    upsert_daily_activity(conn, date(2026, 5, 25), 9000, 6.0, 300, 360)
    a2 = get_daily_activity(conn, date(2026, 5, 25))
    assert a2.steps == 9000

def test_latest_weight_on_or_before(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_daily_weight(conn, date(2026, 5, 20), 72.0)
    upsert_daily_weight(conn, date(2026, 5, 22), 71.5)
    assert get_latest_weight_on_or_before(conn, date(2026, 5, 25)).weight_kg == 71.5

def test_weight_no_time_machine(tmp_path):
    """対象日より未来の体重は使わない（Renpho 遅延同期後の過去日 publish で重要）"""
    conn = open_db(tmp_path / "t.db")
    upsert_daily_weight(conn, date(2026, 5, 22), 71.5)
    upsert_daily_weight(conn, date(2026, 5, 26), 71.0)  # 対象日より未来
    w = get_latest_weight_on_or_before(conn, date(2026, 5, 25))
    assert w.weight_kg == 71.5  # 71.0 は使わない

def test_get_weight_returns_none_when_empty(tmp_path):
    conn = open_db(tmp_path / "t.db")
    assert get_latest_weight_on_or_before(conn, date(2026, 5, 25)) is None
```

- [ ] **Step 2-3: Implement** (rev1 と同等)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(db): daily_activity/weight CRUD + no-time-machine weight fallback"`

---

## Task 2.4: db.py — config + token atomic rotation

**Files:** Modify db.py, tests/test_db.py

- [ ] **Step 1: Tests**

```python
from diet.db import Config, save_config, load_config, Token, save_token_atomic, load_token
from datetime import datetime

def test_config_round_trip(tmp_path):
    conn = open_db(tmp_path / "t.db")
    cfg = Config(birthday=date(1979, 12, 1), height_cm=169, sex="male", timezone="Asia/Tokyo",
                 hpasaneel_path="C:/code/HPasaneel", hpasaneel_diet_root="content/diet",
                 exercise_calorie_source="marginal", bootstrap_daily_kcal=2000)
    save_config(conn, cfg)
    assert load_config(conn) == cfg

def test_config_update_overwrites(tmp_path):
    conn = open_db(tmp_path / "t.db")
    cfg1 = Config(date(1979, 12, 1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None)
    save_config(conn, cfg1)
    cfg2 = Config(date(1979, 12, 1), 170, "male", "Asia/Tokyo", None, "content/diet", "marginal", 2200)
    save_config(conn, cfg2)
    loaded = load_config(conn)
    assert loaded.height_cm == 170
    assert loaded.exercise_calorie_source == "marginal"

def test_token_atomic_replacement(tmp_path):
    conn = open_db(tmp_path / "t.db")
    t1 = Token("A1", "R1", datetime(2026, 12, 31), "UID")
    save_token_atomic(conn, t1)
    t2 = Token("A2", "R2", datetime(2027, 1, 1), "UID")
    save_token_atomic(conn, t2)
    loaded = load_token(conn)
    assert loaded.access_token == "A2"
    n = conn.execute("SELECT COUNT(*) FROM fitbit_token").fetchone()[0]
    assert n == 1
```

- [ ] **Step 2-3: Implement** (rev1 と同等、`BEGIN IMMEDIATE` で囲む)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(db): config save/load + atomic token rotation with BEGIN IMMEDIATE"`

---

# Phase 3: OAuth

## Task 3.1: oauth.py — 自己署名 TLS 証明書生成

**Files:** Create `src/diet/oauth.py`, `tests/test_oauth.py`

(rev1 と同内容、再掲省略。Step 5: `git commit -m "feat(oauth): self-signed TLS cert generation"`)

---

## Task 3.2: oauth.py — auth URL ビルド + HTTPS callback server (manual integration)

**Files:** Modify oauth.py, tests/test_oauth.py

- [ ] **Step 1: Test (URL build only — server は manual E2E)**

```python
from diet.oauth import build_authorization_url, FITBIT_AUTHZ_URL
from urllib.parse import parse_qs, urlparse

def test_build_authz_url_params():
    url = build_authorization_url("CID", "https://localhost:8765/callback", ["activity", "weight"], "state123")
    assert url.startswith(FITBIT_AUTHZ_URL)
    qs = parse_qs(urlparse(url).query)
    assert qs["client_id"] == ["CID"]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == ["https://localhost:8765/callback"]
    assert qs["scope"] == ["activity weight"]
    assert qs["state"] == ["state123"]
```

- [ ] **Step 2-3: Implement** (rev1 と同等)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(oauth): auth URL builder + HTTPS callback server skeleton"`

---

## Task 3.3: oauth.py — token 交換 + refresh

**Files:** Modify oauth.py, tests/test_oauth.py

- [ ] **Step 1: Tests (pytest-httpx で mock)**

```python
import pytest
from diet.oauth import exchange_code_for_token, refresh_access_token

async def test_exchange_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        json={"access_token": "A1", "refresh_token": "R1", "expires_in": 28800, "user_id": "UID", "scope": "activity weight"},
    )
    tok = await exchange_code_for_token("CID", "CSEC", "C1", "https://localhost:8765/callback")
    assert tok.access_token == "A1"
    assert tok.user_id == "UID"

async def test_refresh_returns_new_pair(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        json={"access_token": "A2", "refresh_token": "R2", "expires_in": 28800, "user_id": "UID", "scope": "activity weight"},
    )
    tok = await refresh_access_token("CID", "CSEC", "R1")
    assert tok.access_token == "A2"
    assert tok.refresh_token == "R2"

async def test_exchange_4xx_raises(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        status_code=400, json={"errors": [{"message": "invalid_grant"}]},
    )
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await exchange_code_for_token("CID", "CSEC", "BAD", "https://localhost:8765/callback")
```

- [ ] **Step 2-3: Implement** (rev1 と同等)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(oauth): token exchange + refresh"`

---

# Phase 4: Fitbit クライアント

## Task 4.1: fitbit_client.py — 認証付き HTTP + activity endpoint

**Files:** Create `src/diet/fitbit_client.py`, `tests/test_fitbit_client.py`

- [ ] **Step 1: Tests**

```python
import pytest
from diet.fitbit_client import FitbitClient

async def test_authorization_header(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        json={"summary": {"steps": 100, "marginalCalories": 80, "distances": [{"activity": "total", "distance": 1.5}]}, "activities": []},
        match_headers={"Authorization": "Bearer A1"},
    )
    client = FitbitClient(access_token="A1")
    data = await client.get_activity_summary("2026-05-25")
    assert data["summary"]["steps"] == 100
```

- [ ] **Step 2-3: Implement** (rev1 と同等、最小)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(fitbit): authorized HTTP + activity endpoint"`

---

## Task 4.2: fitbit_client.py — weight endpoint

**Files:** Modify fitbit_client.py, tests/test_fitbit_client.py

- [ ] **Step 1-5: TDD (rev1 と同内容)**

`git commit -m "feat(fitbit): weight endpoint"`

---

## Task 4.3: fitbit_client.py — rate limit 追跡

**Files:** Modify fitbit_client.py, Create `tests/test_fitbit_client_rate_limit.py`

- [ ] **Step 1: Tests**

```python
async def test_rate_limit_headers_tracked(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        json={"summary": {}},
        headers={"Fitbit-Rate-Limit-Limit": "150", "Fitbit-Rate-Limit-Remaining": "120", "Fitbit-Rate-Limit-Reset": "1800"},
    )
    client = FitbitClient(access_token="A1")
    await client.get_activity_summary("2026-05-25")
    assert client.rate_limit.limit == 150
    assert client.rate_limit.remaining == 120
    assert client.rate_limit.reset_seconds == 1800

async def test_429_raises_with_reset_info(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        status_code=429, headers={"Fitbit-Rate-Limit-Reset": "300"}, json={},
    )
    client = FitbitClient(access_token="A1")
    with pytest.raises(Exception) as exc:
        await client.get_activity_summary("2026-05-25")
    assert "300" in str(exc.value) or client.rate_limit.reset_seconds == 300
```

- [ ] **Step 2-3: Implement** RateLimitState 更新ロジック + 429 で reset_seconds 保存

- [ ] **Step 4-5**: Pass, `git commit -m "feat(fitbit): rate limit tracking + 429 with reset info"`

---

## Task 4.4: fitbit_client.py — 401 自動 refresh (single retry)

**Files:** Modify fitbit_client.py, tests/test_fitbit_client.py

- [ ] **Step 1: Tests**

```python
async def test_401_triggers_one_refresh(httpx_mock):
    httpx_mock.add_response(url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json", status_code=401)
    httpx_mock.add_response(url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json", json={"summary": {"steps": 100}})
    calls = {"n": 0}
    async def refresh():
        calls["n"] += 1
        return "A2"
    client = FitbitClient(access_token="A1", on_unauthorized=refresh)
    data = await client.get_activity_summary("2026-05-25")
    assert calls["n"] == 1
    assert client.access_token == "A2"

async def test_401_twice_raises(httpx_mock):
    """refresh しても 401 が続く → 例外で停止 (無限ループ防止)"""
    httpx_mock.add_response(url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json", status_code=401)
    httpx_mock.add_response(url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json", status_code=401)
    async def refresh():
        return "A2"
    client = FitbitClient(access_token="A1", on_unauthorized=refresh)
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_activity_summary("2026-05-25")
```

- [ ] **Step 2-5: Implement, pass, commit**: `git commit -m "feat(fitbit): single-retry 401 with on_unauthorized callback"`

---

# Phase 5: Publish (公開境界)

## Task 5.1: publish.py — PublicDayRecord DTO + to_public_dict

(rev1 と同内容、`git commit -m "feat(publish): PublicDayRecord DTO with hand-written allowlist"`)

---

## Task 5.2: publish.py — JSON schema 定義

**Files:** Modify `src/diet/publish.py`, Create `tests/test_publish_schema.py`

- [ ] **Step 1: Tests (各 schema rule 独立)**

```python
import pytest
from diet.publish import validate_log_json

def test_minimal_valid():
    validate_log_json({"updated_at": "2026-05-25T22:00:00+09:00", "days": []})

def test_rejects_top_level_extra_key():
    with pytest.raises(Exception):
        validate_log_json({"updated_at": "2026-05-25T22:00:00+09:00", "days": [], "secret": "x"})

def test_rejects_day_extra_key():
    """note 等が混入したら絶対 reject"""
    with pytest.raises(Exception):
        validate_log_json({
            "updated_at": "2026-05-25T22:00:00+09:00",
            "days": [{"date": "2026-05-25", "steps": 1, "distance_km": 1.0,
                       "exercise_kcal": 1, "weight_kg": 1.0, "note": "ラーメン"}],
        })

def test_rejects_missing_required():
    with pytest.raises(Exception):
        validate_log_json({"updated_at": "2026-05-25T22:00:00+09:00",
                            "days": [{"date": "2026-05-25", "steps": 1}]})

def test_rejects_negative_numbers():
    with pytest.raises(Exception):
        validate_log_json({"updated_at": "2026-05-25T22:00:00+09:00",
                            "days": [{"date": "2026-05-25", "steps": -1, "distance_km": 1.0,
                                      "exercise_kcal": 1, "weight_kg": 1.0}]})

def test_rejects_invalid_date_format():
    with pytest.raises(Exception):
        validate_log_json({"updated_at": "2026-05-25T22:00:00+09:00",
                            "days": [{"date": "2026/5/25", "steps": 1, "distance_km": 1.0,
                                      "exercise_kcal": 1, "weight_kg": 1.0}]})
```

- [ ] **Step 2-3: Implement** schema dict + `validate_log_json()` (rev1 と同等)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(publish): JSON schema (top-level + days.items additionalProperties:false)"`

---

## Task 5.3: publish.py — 2 段 validate を build_log_json で強制

**Files:** Modify publish.py, Modify tests/test_publish_schema.py

- [ ] **Step 1: Tests (raw load + final write 両段で独立に reject)**

```python
import pytest
from diet.publish import build_log_json, PublicDayRecord
from datetime import date

def test_raw_load_rejects_poisoned_existing_doc():
    """raw load 段: 既存 log.json に note が混入してた → 例外停止"""
    poisoned = {
        "updated_at": "2026-05-25T22:00:00+09:00",
        "days": [{"date": "2026-05-24", "steps": 1, "distance_km": 1.0,
                  "exercise_kcal": 1, "weight_kg": 1.0, "note": "X"}],
    }
    with pytest.raises(Exception):
        build_log_json([], existing_doc=poisoned)

def test_final_write_rejects_poisoned_final_dict(mocker):
    """final write 段が独立に reject できることを証明。

    実装には内部 seam として `_assemble_final_dict(records, existing_doc) -> dict`
    を分離し、build_log_json は `_assemble_final_dict → validate_log_json(final) → return`
    の流れにする。これにより _assemble_final_dict を spy で汚染した状態でも final
    validate 段が確実に呼ばれて reject することを直接証明できる。"""
    import diet.publish as pub
    from diet.publish import build_log_json, PublicDayRecord
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0,
                           exercise_kcal=1, weight_kg=1.0)
    # 内部 seam を spy で置き換え、final dict に毒を注入してから build_log_json に渡す
    real_assemble = pub._assemble_final_dict
    def poisoning(records, existing_doc):
        d = real_assemble(records, existing_doc)
        d["days"][0]["note"] = "LEAK"  # final 段 validate で必ず弾かれるべき
        return d
    mocker.patch.object(pub, "_assemble_final_dict", side_effect=poisoning)
    with pytest.raises(Exception):
        build_log_json([rec], existing_doc=None)

def test_validate_called_twice_when_existing(mocker):
    valid_existing = {"updated_at": "2026-05-25T22:00:00+09:00", "days": []}
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=1.0)
    spy = mocker.spy(__import__("diet.publish", fromlist=["validate_log_json"]), "validate_log_json")
    build_log_json([rec], existing_doc=valid_existing)
    assert spy.call_count == 2  # raw load + final

def test_validate_called_once_when_no_existing(mocker):
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=1.0)
    spy = mocker.spy(__import__("diet.publish", fromlist=["validate_log_json"]), "validate_log_json")
    build_log_json([rec], existing_doc=None)
    assert spy.call_count == 1  # final のみ
```

- [ ] **Step 2-3: Implement** raw load + 最終 validate を内部 seam として分離する設計に:

```python
def _assemble_final_dict(records: list[PublicDayRecord], existing_doc: dict | None) -> dict:
    """Pure function: merge records into existing days, sort, attach updated_at."""
    if existing_doc is not None:
        existing_by_date = {d["date"]: d for d in existing_doc["days"]}
    else:
        existing_by_date = {}
    for r in records:
        existing_by_date[r.date.isoformat()] = r.to_public_dict()
    return {
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "days": sorted(existing_by_date.values(), key=lambda d: d["date"], reverse=True),
    }

def build_log_json(records: list[PublicDayRecord], existing_doc: dict | None) -> dict:
    if existing_doc is not None:
        validate_log_json(existing_doc)        # 段 1: raw load
    final = _assemble_final_dict(records, existing_doc)
    validate_log_json(final)                    # 段 2: final
    return final
```

`_assemble_final_dict` を内部関数として export しておくことで、final 段 reject テストが内部 seam 経由で書ける。

- [ ] **Step 4-5**: Pass, `git commit -m "feat(publish): 2-stage validate (raw load + final write) enforced"`

---

## Task 5.4: publish.py — merge ロジック (他日 entry 保持、対象日のみ差し替え)

**Files:** Modify publish.py, Create `tests/test_publish_merge.py`

- [ ] **Step 1: Tests**

```python
from datetime import date
from diet.publish import build_log_json, PublicDayRecord

def D(dstr, steps=1):
    return {"date": dstr, "steps": steps, "distance_km": 1.0, "exercise_kcal": 1, "weight_kg": 70.0}

def test_merge_preserves_other_dates():
    existing = {"updated_at": "2026-05-25T22:00:00+09:00",
                "days": [D("2026-05-24", steps=100), D("2026-05-23", steps=200)]}
    new = PublicDayRecord(date=date(2026, 5, 25), steps=999, distance_km=1.0, exercise_kcal=1, weight_kg=70.0)
    out = build_log_json([new], existing)
    dates = [d["date"] for d in out["days"]]
    assert "2026-05-25" in dates
    assert "2026-05-24" in dates
    assert "2026-05-23" in dates
    assert len(dates) == 3

def test_merge_replaces_same_date():
    existing = {"updated_at": "2026-05-25T22:00:00+09:00",
                "days": [D("2026-05-25", steps=100)]}
    new = PublicDayRecord(date=date(2026, 5, 25), steps=999, distance_km=1.0, exercise_kcal=1, weight_kg=70.0)
    out = build_log_json([new], existing)
    assert len(out["days"]) == 1
    assert out["days"][0]["steps"] == 999

def test_merge_sorts_by_date_desc():
    existing = {"updated_at": "2026-05-25T22:00:00+09:00",
                "days": [D("2026-05-23"), D("2026-05-25"), D("2026-05-24")]}
    out = build_log_json([], existing)
    dates = [d["date"] for d in out["days"]]
    assert dates == ["2026-05-25", "2026-05-24", "2026-05-23"]
```

- [ ] **Step 2-3: Implement** (build_log_json の merge ロジックを実装)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(publish): merge preserves other dates + replaces target date"`

---

## Task 5.5: publish.py — boundary test (DB → publish の note 漏洩経路)

**Files:** Create `tests/test_publish_boundary.py`

- [ ] **Step 1: Test (DB に note 入れて publish フロー全体を通す)**

```python
from datetime import date, datetime
from pathlib import Path
import json
from diet.db import open_db, insert_intake_event, upsert_daily_activity, upsert_daily_weight
from diet.publish import build_records_from_db, build_log_json, PublicDayRecord

def test_intake_notes_never_reach_log_json(tmp_path):
    """★最重要: intake_events に note を仕込んで publish フロー全体を通す。
    log.json の文字列に note が一切現れないことを検証"""
    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    # 食事 note を仕込む（極めて生々しい文字列）
    insert_intake_event(conn, target, datetime(2026, 5, 25, 12, 0), 600, "append", note="ラーメン特盛 ホルモン定食")
    insert_intake_event(conn, target, datetime(2026, 5, 25, 19, 0), 1200, "override", note="焼肉食べ放題 ビール 5杯")
    # 公開対象データ
    upsert_daily_activity(conn, target, steps=8234, distance_km=5.3, logged_activities_kcal=280, marginal_kcal=340)
    upsert_daily_weight(conn, target, 71.2)
    # build_records_from_db は内部で intake_events を SELECT してはならない
    records = build_records_from_db(conn, target_dates=[target], exercise_calorie_source="marginal")
    out = build_log_json(records, existing_doc=None)
    serialized = json.dumps(out, ensure_ascii=False)
    # 直接の文字列禁忌
    for forbidden in ["ラーメン", "焼肉", "ホルモン", "ビール", "特盛", "食べ放題"]:
        assert forbidden not in serialized
    # フィールド名禁忌
    for forbidden_field in ["note", "intake_kcal", "intake", "kcal_intake", "menu"]:
        assert forbidden_field not in serialized

def test_publish_function_does_not_select_intake_events(tmp_path):
    """build_records_from_db が intake_events テーブルを参照しないこと。
    sqlite3.Connection.execute は C-level read-only 属性なので patch できない。
    set_trace_callback を使って実際に走った全 SQL をキャプチャする"""
    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    upsert_daily_activity(conn, target, steps=1, distance_km=1.0, logged_activities_kcal=1, marginal_kcal=1)
    upsert_daily_weight(conn, target, 70.0)
    captured_sql = []
    conn.set_trace_callback(captured_sql.append)
    build_records_from_db(conn, target_dates=[target], exercise_calorie_source="marginal")
    conn.set_trace_callback(None)
    intake_sqls = [s for s in captured_sql if "intake_events" in s.lower()]
    assert intake_sqls == [], f"publish path touched intake_events: {intake_sqls}"

def test_publish_function_only_selects_allowed_tables(tmp_path):
    """publish 関数が触ってよいテーブルは daily_activity と daily_weight のみ。
    JOIN intake_events のような巧妙な漏洩経路も検出"""
    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    upsert_daily_activity(conn, target, 1, 1.0, 1, 1)
    upsert_daily_weight(conn, target, 70.0)
    captured = []
    conn.set_trace_callback(captured.append)
    build_records_from_db(conn, target_dates=[target], exercise_calorie_source="marginal")
    conn.set_trace_callback(None)
    forbidden_tables = ["intake_events", "config", "fitbit_token"]
    for sql in captured:
        for t in forbidden_tables:
            assert t not in sql.lower(), f"publish touched forbidden table {t}: {sql}"
```

- [ ] **Step 2-3: Implement `build_records_from_db()` in publish.py**

```python
def build_records_from_db(conn, target_dates: list[date], exercise_calorie_source: str) -> list[PublicDayRecord]:
    """Public boundary: SELECTS ONLY daily_activity + daily_weight. Never reads intake_events."""
    from diet.db import get_daily_activity, get_latest_weight_on_or_before
    records = []
    for d in target_dates:
        a = get_daily_activity(conn, d)
        w = get_latest_weight_on_or_before(conn, d)
        if a is None or w is None:
            continue
        if exercise_calorie_source == "marginal":
            ex = a.marginal_kcal or 0
        elif exercise_calorie_source == "logged_activities":
            ex = a.logged_activities_kcal or 0
        else:
            ex = a.marginal_kcal or 0
        records.append(PublicDayRecord(date=d, steps=a.steps, distance_km=a.distance_km,
                                        exercise_kcal=ex, weight_kg=w.weight_kg))
    return records
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(publish): build_records_from_db with intake_events isolation boundary test"`

---

## Task 5.6: publish.py — git 操作 (status check + pull --rebase + stage one + commit + push)

**Files:** Modify publish.py, Create `tests/test_publish_git.py`

- [ ] **Step 1: Tests (実 git で tmp_path に repo を作って動作確認)**

```python
import subprocess
from pathlib import Path
from datetime import date
from diet.publish import publish_to_hpasaneel, PublicDayRecord

def _init_repo(p: Path):
    subprocess.run(["git", "init"], cwd=p, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=p, check=True)
    (p / "README.md").write_text("# t")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=p, check=True, capture_output=True)

def test_publish_creates_log_and_commits(tmp_path):
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=50, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    log_file = repo / "content/diet/log.json"
    assert log_file.exists()
    assert "2026-05-25" in log_file.read_text()
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, check=True, capture_output=True, text=True)
    assert "diet:" in log.stdout

def test_publish_stages_only_log_json(tmp_path):
    """他の untracked ファイルがあっても、log.json だけ commit する"""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    (repo / "untracked.txt").write_text("should not be committed")
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=50, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    # untracked.txt は untracked のまま
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True)
    assert "?? untracked.txt" in status.stdout
```

- [ ] **Step 2-3: Implement** (rev1 と同等、`git add` は log.json 限定指定、do_push=False で pull/push 両方 skip)

- [ ] **Step 4-5**: Pass, `git commit -m "feat(publish): git operations with limited stage scope"`

---

## Task 5.7: publish.py — log.json 手動変更時の確認プロンプト

**Files:** Modify publish.py, tests/test_publish_git.py

- [ ] **Step 1: Test**

```python
from unittest.mock import patch

def test_publish_aborts_on_manual_log_changes(tmp_path):
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    # 初回 publish
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=50, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    # log.json を手動で変更（commit せず）
    log_file = repo / "content/diet/log.json"
    log_file.write_text(log_file.read_text() + "\n# manual mess")
    # 次回 publish はユーザー確認を求める → no で中止
    rec2 = PublicDayRecord(date=date(2026, 5, 26), steps=2, distance_km=2.0, exercise_kcal=60, weight_kg=70.0)
    with patch("click.confirm", return_value=False):
        import pytest
        with pytest.raises(SystemExit):
            publish_to_hpasaneel(repo, "content/diet", [rec2], do_push=False)
```

- [ ] **Step 2-3: Implement** publish_to_hpasaneel 内で `git status --porcelain content/diet/log.json` が空でなければ click.confirm を呼ぶ、no なら sys.exit(1)。

- [ ] **Step 4-5**: Pass, `git commit -m "feat(publish): abort on manual log.json changes without confirm"`

---

# Phase 6: CLI コマンド (1 コマンド = 1 タスク)

## Task 6.1: cli.py — diet init (config + cert + OAuth + 初回 sync)

**Files:** Modify cli.py, Modify oauth.py, Create tests/test_cli_init.py

- [ ] **Step 1: Tests**

```python
from click.testing import CliRunner
from diet.cli import app

def test_init_writes_config_and_runs_oauth_and_sync(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    oauth_spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    sync_spy = mocker.patch("diet.cli._run_initial_sync", return_value=None)
    runner = CliRunner()
    inputs = "1979-12-01\n169\nmale\n\nC:/code/HPasaneel\ncontent/diet\n2000\n"
    result = runner.invoke(app, ["init"], input=inputs)
    assert result.exit_code == 0, result.output
    db = (tmp_path / "diet.db")
    assert db.exists()
    from diet.db import open_db, load_config
    cfg = load_config(open_db(db))
    assert cfg.height_cm == 169
    assert cfg.bootstrap_daily_kcal == 2000
    oauth_spy.assert_called_once()
    sync_spy.assert_called_once()
    # 過去 30 日 sync を呼ぶこと (spec § 8.3)
    args, kwargs = sync_spy.call_args
    assert kwargs.get("days") == 30 or (len(args) >= 2 and args[1] == 30)

def test_init_baseline_skip_with_enter(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    mocker.patch("diet.oauth.run_init_flow", return_value=None)
    mocker.patch("diet.cli._run_initial_sync", return_value=None)
    runner = CliRunner()
    inputs = "1979-12-01\n169\nmale\n\nC:/code/HPasaneel\ncontent/diet\n\n"  # baseline 空
    result = runner.invoke(app, ["init"], input=inputs)
    from diet.db import open_db, load_config
    cfg = load_config(open_db(tmp_path / "diet.db"))
    assert cfg.bootstrap_daily_kcal is None
```

- [ ] **Step 2-3: Implement**

```python
# src/diet/cli.py
import os
from pathlib import Path
import click
from diet.db import open_db, save_config, Config

def _data_dir() -> Path:
    return Path(os.environ.get("DIET_DATA_DIR", "data"))

@app.command()
@click.option("--port", default=8765, type=int)
def init(port: int) -> None:
    """First-time setup."""
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    birthday = click.prompt("生年月日 (YYYY-MM-DD)", type=click.DateTime(formats=["%Y-%m-%d"]))
    height = click.prompt("身長 (cm)", type=int)
    sex = click.prompt("性別 (male/female)", type=click.Choice(["male", "female"]))
    tz = click.prompt("タイムゾーン", default="Asia/Tokyo")
    hpath = click.prompt("HPasaneel リポジトリパス", default="C:/code/HPasaneel")
    droot = click.prompt("HPasaneel ダッシュボードルート", default="content/diet")
    bootstrap_in = click.prompt("普段 1 日のカロリー目安 (不明なら Enter で skip)", default="", show_default=False)
    bootstrap_val = int(bootstrap_in) if bootstrap_in.strip() else None
    cfg = Config(birthday=birthday.date(), height_cm=height, sex=sex, timezone=tz,
                  hpasaneel_path=hpath, hpasaneel_diet_root=droot,
                  exercise_calorie_source=None, bootstrap_daily_kcal=bootstrap_val)
    conn = open_db(data_dir / "diet.db")
    save_config(conn, cfg)
    click.echo("config saved.")
    from diet.oauth import run_init_flow
    run_init_flow(data_dir=data_dir, port=port, conn=conn)
    _run_initial_sync(conn, days=30)
    click.echo("初期 sync 完了。`diet calibrate` で exercise_calorie_source を決めてください。")

def _run_initial_sync(conn, days: int):
    """Internal: 過去 N 日の Fitbit data を取得して DB に保存。"""
    # 詳細は Task 6.2 (sync) と共有。ここでは関数 stub を定義し、Task 6.2 で本実装。
    from diet.cli_helpers import run_sync_async
    import asyncio
    asyncio.run(run_sync_async(conn, days=days))
```

`diet/cli_helpers.py` 新規 (内部関数):
```python
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import os
from diet.db import load_config, load_token, save_token_atomic, upsert_daily_activity, upsert_daily_weight
from diet.fitbit_client import FitbitClient
from diet.oauth import refresh_access_token

async def run_sync_async(conn, days: int):
    cfg = load_config(conn)
    tok = load_token(conn)
    if tok is None:
        raise RuntimeError("Not authenticated. Run `diet init` first.")
    tz = ZoneInfo(cfg.timezone)
    today = datetime.now(tz).date()

    async def refresh():
        new_tok = await refresh_access_token(
            os.environ["FITBIT_CLIENT_ID"], os.environ["FITBIT_CLIENT_SECRET"], tok.refresh_token,
        )
        save_token_atomic(conn, new_tok)
        return new_tok.access_token

    client = FitbitClient(access_token=tok.access_token, on_unauthorized=refresh)
    for offset in range(days):
        d = today - timedelta(days=offset)
        try:
            act = await client.get_activity_summary(d.isoformat())
            summary = act["summary"]
            distance_km = next((x["distance"] for x in summary.get("distances", []) if x["activity"] == "total"), 0.0)
            logged = sum(a.get("calories", 0) for a in act.get("activities", []))
            marginal = summary.get("marginalCalories", 0)
            upsert_daily_activity(conn, d, steps=summary.get("steps", 0), distance_km=distance_km,
                                    logged_activities_kcal=logged, marginal_kcal=marginal)
            weights = await client.get_weight_log(d.isoformat())
            for w in weights:
                upsert_daily_weight(conn, date.fromisoformat(w["date"]), float(w["weight"]))
        except Exception as e:
            print(f"sync warning ({d}): {e}", flush=True)
            continue
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet init with initial sync"`

---

## Task 6.2: cli.py — diet sync

**Files:** Modify cli.py, Create tests/test_cli_sync.py

- [ ] **Step 1: Tests**

```python
def test_sync_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    runner = CliRunner()
    result = runner.invoke(app, ["sync"])
    assert result.exit_code != 0
    assert "not authenticated" in result.output.lower() or "init" in result.output.lower()

def test_sync_calls_fitbit_client(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config, Token, save_token_atomic
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    save_token_atomic(conn, Token("A1", "R1", datetime(2030,1,1), "UID"))
    spy = mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--days", "3"])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
```

- [ ] **Step 2-3: Implement**

```python
@app.command()
@click.option("--days", default=7, type=int)
def sync(days: int) -> None:
    """Fetch Fitbit activity + weight for the last N days."""
    import asyncio
    conn = open_db(_data_dir() / "diet.db")
    from diet.db import load_token
    if load_token(conn) is None:
        raise click.ClickException("Not authenticated. Run `diet init` first.")
    from diet.cli_helpers import run_sync_async
    asyncio.run(run_sync_async(conn, days=days))
    click.echo(f"sync complete ({days} days)")
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet sync command"`

---

## Task 6.3: cli.py — diet calibrate

**Files:** Modify cli.py, Create tests/test_cli_calibrate.py

- [ ] **Step 1: Tests**

```python
def test_calibrate_displays_recent_calories(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config, upsert_daily_activity
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    for offset in range(5):
        d = date(2026, 5, 25) - __import__("datetime").timedelta(days=offset)
        upsert_daily_activity(conn, d, steps=8000+offset*100, distance_km=5.0, logged_activities_kcal=200+offset*10, marginal_kcal=300+offset*10)
    runner = CliRunner()
    result = runner.invoke(app, ["calibrate"], input="marginal\n")
    assert result.exit_code == 0
    assert "logged_activities" in result.output
    assert "marginal" in result.output
    cfg = __import__("diet.db", fromlist=["load_config"]).load_config(conn)
    assert cfg.exercise_calorie_source == "marginal"

def test_calibrate_decide_later_keeps_source_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config, load_config
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    runner = CliRunner()
    result = runner.invoke(app, ["calibrate"], input="decide_later\n")
    assert result.exit_code == 0
    cfg = load_config(conn)
    assert cfg.exercise_calorie_source is None
```

- [ ] **Step 2-3: Implement**

`src/diet/calibrate.py`:
```python
from datetime import date, timedelta
import click
from dataclasses import replace
from diet.db import open_db, load_config, save_config, get_daily_activity

def run_calibrate(data_dir, days: int = 14) -> None:
    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    today = date.today()
    click.echo(f"過去 {days} 日の Fitbit カロリー候補:")
    click.echo(f"{'date':<12} {'steps':>8} {'distance_km':>12} {'logged_activities':>18} {'marginal':>10}")
    for offset in range(days):
        d = today - timedelta(days=offset)
        a = get_daily_activity(conn, d)
        if a is None:
            continue
        click.echo(f"{d.isoformat():<12} {a.steps:>8,} {a.distance_km:>12.1f} "
                   f"{(a.logged_activities_kcal or 0):>18,} {(a.marginal_kcal or 0):>10,}")
    click.echo("\n候補の意味:")
    click.echo("  logged_activities: 明示的に記録された運動エントリの合計")
    click.echo("  marginal:          Fitbit が活動由来と推定した分（基礎代謝含まず、推奨デフォルト）")
    choice = click.prompt("採用する exercise_calorie_source",
                          type=click.Choice(["logged_activities", "marginal", "decide_later"]),
                          default="marginal")
    if choice == "decide_later":
        click.echo("source 未確定、当面 marginal で仮計算します。")
        return
    save_config(conn, replace(cfg, exercise_calorie_source=choice))
    click.echo(f"exercise_calorie_source = {choice} を config に保存しました。")
```

cli.py に追加:
```python
@app.command()
@click.option("--days", default=14, type=int)
def calibrate(days: int) -> None:
    """Show recent Fitbit calorie candidates and select exercise_calorie_source."""
    from diet.calibrate import run_calibrate
    run_calibrate(_data_dir(), days=days)
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet calibrate command"`

---

## Task 6.4: cli.py — diet weight

**Files:** Modify cli.py, Create tests/test_cli_weight.py

- [ ] **Step 1: Tests**

```python
def test_weight_inserts_today(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config, get_latest_weight_on_or_before
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    runner = CliRunner()
    result = runner.invoke(app, ["weight", "71.2"])
    assert result.exit_code == 0
    w = get_latest_weight_on_or_before(conn, date.today())
    assert w.weight_kg == 71.2

def test_weight_with_date_option(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config, get_latest_weight_on_or_before
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    runner = CliRunner()
    result = runner.invoke(app, ["weight", "70.5", "--date", "2026-05-20"])
    assert result.exit_code == 0
    w = get_latest_weight_on_or_before(conn, date(2026, 5, 20))
    assert w.weight_kg == 70.5
```

- [ ] **Step 2-3: Implement**

```python
@app.command()
@click.argument("kg", type=float)
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD (default today)")
def weight(kg: float, date_str: str | None) -> None:
    from diet.db import upsert_daily_weight
    from datetime import date as _date
    from zoneinfo import ZoneInfo
    from datetime import datetime
    conn = open_db(_data_dir() / "diet.db")
    cfg = __import__("diet.db", fromlist=["load_config"]).load_config(conn)
    target = _date.fromisoformat(date_str) if date_str else datetime.now(ZoneInfo(cfg.timezone)).date()
    upsert_daily_weight(conn, target, kg)
    click.echo(f"weight {kg}kg recorded for {target}")
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet weight manual entry"`

---

## Task 6.5: cli.py — diet baseline

**Files:** Modify cli.py, Create tests/test_cli_baseline.py

- [ ] **Step 1: Test**

```python
def test_baseline_updates_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config, load_config
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    runner = CliRunner()
    result = runner.invoke(app, ["baseline", "2200"])
    assert result.exit_code == 0
    cfg = load_config(conn)
    assert cfg.bootstrap_daily_kcal == 2200
```

- [ ] **Step 2-3: Implement**

```python
@app.command()
@click.argument("kcal", type=int)
def baseline(kcal: int) -> None:
    """Update bootstrap_daily_kcal."""
    from diet.db import load_config, save_config
    from dataclasses import replace
    conn = open_db(_data_dir() / "diet.db")
    cfg = load_config(conn)
    save_config(conn, replace(cfg, bootstrap_daily_kcal=kcal))
    click.echo(f"baseline updated to {kcal} kcal/day")
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet baseline command"`

---

## Task 6.6: cli.py — diet show (display-only)

**Files:** Modify cli.py, Create tests/test_cli_show.py

- [ ] **Step 1: Tests**

```python
def test_show_displays_decision_without_input_or_publish(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config, insert_intake_event, upsert_daily_activity, upsert_daily_weight
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", "marginal", 2000))
    upsert_daily_activity(conn, date(2026, 5, 25), 8000, 5.0, 250, 300)
    upsert_daily_weight(conn, date(2026, 5, 25), 71.2)
    insert_intake_event(conn, date(2026, 5, 25), datetime(2026, 5, 25, 12, 0), 2000, "override")
    # publish が呼ばれないことを確認
    publish_spy = mocker.patch("diet.publish.publish_to_hpasaneel")
    runner = CliRunner()
    result = runner.invoke(app, ["show", "--date", "2026-05-25"])
    assert result.exit_code == 0
    assert "2,000" in result.output or "2000" in result.output
    publish_spy.assert_not_called()
```

- [ ] **Step 2-3: Implement**

`src/diet/orchestrator.py` に追加:
```python
def run_show_only(data_dir: Path, target_date: _date) -> None:
    """Display-only mode: no intake prompt, no publish. Reuses the same calculation."""
    from diet.db import (open_db, load_config, get_events_for_date, get_events_in_range,
                          get_daily_activity, get_latest_weight_on_or_before)
    from diet.bmr import age_at, mifflin_st_jeor
    from diet.intake import past_avg, decide_intake_kcal
    from diet.formatters import format_intake_display, format_balance
    from diet.helpers import resolve_exercise_kcal
    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    activity = get_daily_activity(conn, target_date)
    weight = get_latest_weight_on_or_before(conn, target_date)
    history = get_events_in_range(conn, target_date - timedelta(days=14), target_date)
    avg, n = past_avg(history, target_date)
    today_events = get_events_for_date(conn, target_date)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    click.echo(format_intake_display(decision))
    if weight and activity:
        age = age_at(cfg.birthday, target_date)
        bmr = mifflin_st_jeor(weight.weight_kg, cfg.height_cm, age, cfg.sex)
        exercise = resolve_exercise_kcal(activity, cfg.exercise_calorie_source)
        click.echo(format_balance(decision.intake_kcal, bmr, exercise,
                                   activity.steps, activity.distance_km, weight.weight_kg))
```

cli.py:
```python
@app.command()
@click.option("--date", "date_str", default=None)
def show(date_str: str | None) -> None:
    """Display-only mode."""
    from datetime import date as _date, datetime
    from zoneinfo import ZoneInfo
    from diet.orchestrator import run_show_only
    conn = open_db(_data_dir() / "diet.db")
    from diet.db import load_config
    cfg = load_config(conn)
    target = _date.fromisoformat(date_str) if date_str else datetime.now(ZoneInfo(cfg.timezone)).date()
    run_show_only(_data_dir(), target)
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet show display-only mode"`

---

## Task 6.7: cli.py — diet auth (re-authentication)

**Files:** Modify cli.py, Create tests/test_cli_auth.py

- [ ] **Step 1: Test**

```python
def test_auth_calls_oauth_flow(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    spy = mocker.patch("diet.oauth.run_init_flow")
    runner = CliRunner()
    result = runner.invoke(app, ["auth"])
    assert result.exit_code == 0
    spy.assert_called_once()
```

- [ ] **Step 2-3: Implement**

```python
@app.command()
@click.option("--port", default=8765, type=int)
@click.option("--regen-cert", is_flag=True, help="証明書を再生成 (期限切れ時)")
def auth(port: int, regen_cert: bool) -> None:
    """Re-run OAuth (when refresh fails or cert expired)."""
    from diet.oauth import run_init_flow, generate_self_signed_cert
    conn = open_db(_data_dir() / "diet.db")
    if regen_cert:
        # 削除した上で eager に再生成する。run_init_flow を mock しても cert は出来てる
        cert = _data_dir() / "oauth_cert.pem"
        key = _data_dir() / "oauth_key.pem"
        cert.unlink(missing_ok=True)
        key.unlink(missing_ok=True)
        generate_self_signed_cert(cert, key, "localhost", days_valid=3650)
    run_init_flow(data_dir=_data_dir(), port=port, conn=conn)
```

注: `run_init_flow` も内部で `generate_self_signed_cert` を呼ぶが、同じ実装は両ファイル存在時に no-op なので問題ない。`--regen-cert` 時のみ削除 → 即再生成で、run_init_flow が mock されても確実に新しい cert/key が存在する。

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): diet auth + --regen-cert"`

---

## Task 6.8: cli.py — default bare `diet` command (no args)

**Files:** Modify cli.py, Create tests/test_cli_default.py

- [ ] **Step 1: Test**

```python
def test_diet_no_args_calls_orchestrator(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config, Token, save_token_atomic
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", "marginal", 2000))
    save_token_atomic(conn, Token("A1", "R1", datetime(2030,1,1), "UID"))
    spy = mocker.patch("diet.orchestrator.run_daily_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, [])  # 引数なし
    assert result.exit_code == 0
    spy.assert_called_once()

def test_diet_with_date_option(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    from diet.db import open_db, Config, save_config
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", "marginal", 2000))
    spy = mocker.patch("diet.orchestrator.run_daily_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["--date", "2026-05-23"])
    assert result.exit_code == 0
    args, kwargs = spy.call_args
    # target_date=date(2026,5,23) で呼ばれること
    assert "target_date" in kwargs or any(a == date(2026, 5, 23) for a in args)
```

- [ ] **Step 2-3: Implement**

```python
@click.group(invoke_without_command=True)
@click.option("--date", "date_str", default=None, type=str, help="YYYY-MM-DD")
@click.pass_context
def app(ctx: click.Context, date_str: str | None) -> None:
    if ctx.invoked_subcommand is None:
        from datetime import date as _date
        from diet.orchestrator import run_daily_flow
        target = _date.fromisoformat(date_str) if date_str else None
        run_daily_flow(data_dir=_data_dir(), target_date=target)
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(cli): default bare 'diet' command + --date option"`

---

# Phase 7: Orchestrator + Formatters

## Task 7.1: formatters.py — 各 label の表示文字列

**Files:** Create `src/diet/formatters.py`, `tests/test_formatters.py`

- [ ] **Step 1: Tests (7 ケース + balance display)**

```python
from diet.formatters import format_intake_display, format_balance
from diet.intake import IntakeDecision

def test_format_recorded_authoritative():
    d = IntakeDecision(intake_kcal=1800, label="recorded_authoritative", n_samples=10)
    s = format_intake_display(d)
    assert "1,800" in s
    assert "記録" in s

def test_format_recorded_partial_high():
    d = IntakeDecision(intake_kcal=2400, label="recorded_partial_high", n_samples=11)
    s = format_intake_display(d)
    assert "2,400" in s
    assert "部分入力" in s

def test_format_estimated_avg_supplement():
    d = IntakeDecision(intake_kcal=2100, label="estimated_avg_supplement",
                        recorded_part=500, supplement_part=1600, n_samples=11)
    s = format_intake_display(d)
    assert "推定" in s
    assert "2,100" in s
    assert "500" in s
    assert "1,600" in s
    assert "N=11" in s or "N = 11" in s

def test_format_estimated_baseline():
    d = IntakeDecision(intake_kcal=2000, label="estimated_baseline", n_samples=2)
    s = format_intake_display(d)
    assert "baseline" in s.lower() or "推定" in s

def test_format_unconfirmed():
    d = IntakeDecision(intake_kcal=None, label="unconfirmed", n_samples=0)
    s = format_intake_display(d)
    assert "未確定" in s or "unconfirmed" in s

def test_format_balance_red():
    s = format_balance(intake_kcal=2300, bmr=1543, exercise_kcal=280, steps=8234, distance_km=5.3, weight_kg=71.2)
    assert "2,300" in s
    assert "1,543" in s
    assert "280" in s
    assert "-477" in s or "赤字" in s
```

- [ ] **Step 2-3: Implement**

```python
# src/diet/formatters.py
from diet.intake import IntakeDecision

def format_intake_display(d: IntakeDecision) -> str:
    if d.label == "recorded_authoritative":
        return f"摂取 {d.intake_kcal:,} kcal (記録)"
    if d.label == "recorded_partial_high":
        return f"摂取 {d.intake_kcal:,} kcal (部分入力、過去平均超え)"
    if d.label == "estimated_avg_supplement":
        return f"摂取 推定 {d.intake_kcal:,} kcal (記録 {d.recorded_part:,} + 平均補完 {d.supplement_part:,}、N={d.n_samples})"
    if d.label == "estimated_baseline_supplement":
        return f"摂取 推定 {d.intake_kcal:,} kcal (記録 {d.recorded_part:,} + baseline 補完 {d.supplement_part:,})"
    if d.label == "recorded_no_baseline":
        return f"摂取 記録 {d.intake_kcal:,} kcal (cold start、baseline 未設定)"
    if d.label == "estimated_avg":
        return f"摂取 推定 {d.intake_kcal:,} kcal (過去 14 日 complete day 平均, N={d.n_samples})"
    if d.label == "estimated_baseline":
        return f"摂取 推定 {d.intake_kcal:,} kcal (init baseline、N={d.n_samples} < SAMPLE_FLOOR)"
    if d.label == "unconfirmed":
        return "摂取量未確定 (記録なし、過去データ不足、baseline 未設定)"
    raise ValueError(f"unknown label: {d.label}")

def format_balance(intake_kcal: int | None, bmr: float, exercise_kcal: int,
                   steps: int, distance_km: float, weight_kg: float) -> str:
    if intake_kcal is None:
        return "(収支算出不可: 摂取量未確定)"
    burn = bmr + exercise_kcal
    balance = intake_kcal - burn
    if balance < 0:
        label = "赤字"
        # 黒字化までの追加歩数 = (-balance) / (kcal/step)
        # ざっくり 70kg * 0.0005 = 0.035 kcal/歩 (Mifflin の歩行)
        extra_steps = int(-balance / 0.035) if weight_kg else 0
        extra_km = -balance / 60.0  # 60 kcal/km 想定
        return (f"摂取 {intake_kcal:,} vs 消費 (BMR {int(bmr):,} + 運動 {exercise_kcal:,}) "
                f"= {balance:+,} kcal ({label})\n    黒字化まで あと約 {extra_steps:,} 歩 (または 走 {extra_km:.1f}km)")
    return f"摂取 {intake_kcal:,} vs 消費 (BMR {int(bmr):,} + 運動 {exercise_kcal:,}) = {balance:+,} kcal (黒字)"
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(formatters): all 7 intake labels + balance display"`

---

## Task 7.2: orchestrator.py — 5 ステップ対話フロー

**Files:** Create `src/diet/orchestrator.py`, `tests/test_orchestrator_e2e.py`

- [ ] **Step 1: Tests (E2E with mocks for I/O)**

```python
def test_orchestrator_complete_day_no_publish(tmp_path, monkeypatch, mocker):
    """完全な日 (=2300) を記録して publish なし"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config, Token, save_token_atomic, upsert_daily_activity, upsert_daily_weight
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", str(tmp_path / "fake_hp"), "content/diet", "marginal", 2000))
    save_token_atomic(conn, Token("A1", "R1", datetime(2030,1,1), "UID"))
    upsert_daily_activity(conn, target, steps=8234, distance_km=5.3, logged_activities_kcal=280, marginal_kcal=300)
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", side_effect=["=2300"])
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    # 食事 event 1 件記録、publish はされてない
    from diet.db import get_events_for_date
    events = get_events_for_date(conn, target)
    assert len(events) == 1
    assert events[0].kcal == 2300
    assert events[0].op == "override"

def test_orchestrator_skip_intake_uses_avg(tmp_path, monkeypatch, mocker):
    """Enter で skip、過去 complete day 平均で推定して表示される"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import (open_db, Config, save_config, Token, save_token_atomic,
                          insert_intake_event, upsert_daily_activity, upsert_daily_weight)
    from datetime import date, datetime, timedelta
    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo",
                              str(tmp_path / "fake_hp"), "content/diet", "marginal", 2200))
    save_token_atomic(conn, Token("A1","R1", datetime(2030,1,1), "UID"))
    # 過去 14 日 complete day with =2000
    for i in range(1, 15):
        d = target - timedelta(days=i)
        insert_intake_event(conn, d, datetime(d.year, d.month, d.day, 12, 0), 2000, "override")
    upsert_daily_activity(conn, target, steps=8000, distance_km=5.0,
                          logged_activities_kcal=250, marginal_kcal=300)
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", return_value="")  # 食事 skip
    mocker.patch("click.confirm", return_value=False)  # publish skip
    capture = []
    mocker.patch("click.echo", side_effect=lambda *a, **k: capture.append(" ".join(str(x) for x in a)))
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    out = "\n".join(capture)
    assert "推定" in out and "2,000" in out
    assert "N=14" in out or "N = 14" in out
```

- [ ] **Step 2-3: Implement** in `src/diet/orchestrator.py`:

```python
import asyncio
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import click

def run_daily_flow(data_dir: Path, target_date: _date | None = None) -> None:
    from diet.db import (open_db, load_config, get_events_for_date, get_events_in_range,
                          insert_intake_event, get_daily_activity, get_latest_weight_on_or_before)
    from diet.bmr import age_at, mifflin_st_jeor
    from diet.intake import past_avg, decide_intake_kcal
    from diet.publish import build_records_from_db, publish_to_hpasaneel
    from diet.formatters import format_intake_display, format_balance
    from diet.cli_helpers import run_sync_async
    from diet.helpers import resolve_exercise_kcal

    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException("Not initialized. Run `diet init` first.")
    tz = ZoneInfo(cfg.timezone)
    today = target_date or datetime.now(tz).date()

    # [1] Fitbit sync (failure tolerated)
    click.echo(f"[1/5 Fitbit同期] 取得中...")
    try:
        asyncio.run(run_sync_async(conn, days=7))
    except Exception as e:
        click.echo(f"  ⚠ sync failed: {e} (オフラインで続行)")

    activity = get_daily_activity(conn, today)
    weight = get_latest_weight_on_or_before(conn, today)
    if activity:
        click.echo(f"  歩数 {activity.steps:,} / 距離 {activity.distance_km:.1f}km")
    if weight:
        click.echo(f"  体重 {weight.weight_kg}kg ({weight.date} 計測)")

    # [2] 食事入力
    cur_events = get_events_for_date(conn, today)
    from diet.intake import recorded_sum as _recorded_sum
    cur_sum = _recorded_sum(cur_events) or 0  # ★ op semantics に従って計算（自前で再実装しない）
    user_in = click.prompt(f"[2/5 食事入力] 累積 {cur_sum} kcal、入力 (+追加 / =上書き / Enter=skip)",
                            default="", show_default=False)
    _handle_intake_input(conn, today, user_in.strip())

    # [3] BMR
    if weight is None:
        click.echo("[3/5 BMR] 体重データなしのため算出不可")
        bmr = None
    else:
        age = age_at(cfg.birthday, today)
        bmr = mifflin_st_jeor(weight.weight_kg, cfg.height_cm, age, cfg.sex)
        click.echo(f"[3/5 BMR] {age}歳 / {cfg.height_cm}cm / {weight.weight_kg}kg → {int(bmr):,} kcal")

    # [4] 収支
    history = get_events_in_range(conn, today - timedelta(days=14), today)
    avg, n = past_avg(history, today)
    today_events = get_events_for_date(conn, today)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    exercise = resolve_exercise_kcal(activity, cfg.exercise_calorie_source) if activity else 0
    click.echo("[4/5 収支]")
    click.echo("  " + format_intake_display(decision))
    if bmr is not None and weight is not None:
        click.echo("  " + format_balance(decision.intake_kcal, bmr, exercise,
                                          activity.steps, activity.distance_km, weight.weight_kg))

    # [5] publish
    if not click.confirm("[5/5 公開] HPasaneel に運動・体重のみ公開しますか?"):
        return
    if cfg.hpasaneel_path is None or activity is None or weight is None:
        click.echo("  publish skip: required data missing")
        return
    records = build_records_from_db(conn, [today], cfg.exercise_calorie_source or "marginal")
    publish_to_hpasaneel(Path(cfg.hpasaneel_path), cfg.hpasaneel_diet_root, records, do_push=True)
    click.echo("  publish 完了")

def _handle_intake_input(conn, target: _date, raw: str) -> None:
    from diet.db import insert_intake_event
    if not raw:
        return
    now = datetime.now()
    if raw.startswith("+"):
        kcal = int(raw[1:])
        insert_intake_event(conn, target, now, kcal, "append")
    elif raw.startswith("="):
        kcal = int(raw[1:])
        insert_intake_event(conn, target, now, kcal, "override")
    else:
        raise click.ClickException(f"unrecognized input: {raw!r} (+追加 or =上書き or Enter)")
```

`src/diet/helpers.py`:
```python
def resolve_exercise_kcal(activity, source: str | None) -> int:
    if activity is None:
        return 0
    if source == "logged_activities":
        return activity.logged_activities_kcal or 0
    return activity.marginal_kcal or 0  # default: marginal
```

- [ ] **Step 4-5**: Pass, `git commit -m "feat(orchestrator): 5-step daily flow with offline tolerance"`

---

# Phase 8: HPasaneel ダッシュボード

## Task 8.1: HPasaneel 既存規約調査 + recharts 依存追加

**Files:**
- Inspect: `C:/code/HPasaneel/` 既存構造
- Modify: `C:/code/HPasaneel/package.json`
- Create: `C:/code/HPasaneel/content/diet/log.json` (空 doc)

- [ ] **Step 1: 既存規約確認**

```bash
cd C:/code/HPasaneel
cat package.json                                  # next 15, react 19 確認
ls app/                                            # ルート構造、layout.tsx 確認
grep -r "use client" app/ | head                  # client component の既存パターン
cat tsconfig.json                                  # path alias 確認
npm run lint                                       # 既存 lint 状態を baseline 取得
npm run build                                      # build が通る baseline
```

- [ ] **Step 2: recharts 追加**

```bash
cd C:/code/HPasaneel
npm install recharts
```

- [ ] **Step 3: log.json placeholder**

`C:/code/HPasaneel/content/diet/log.json`:
```json
{
  "updated_at": "2026-05-25T00:00:00+09:00",
  "days": []
}
```

- [ ] **Step 4: build + lint 確認**

```bash
npm run lint
npm run build
```
Expected: 既存 baseline と同等、新規 warning なし。

- [ ] **Step 5: Commit (HPasaneel 側)**

```bash
cd C:/code/HPasaneel
git add package.json package-lock.json content/diet/log.json
git commit -m "feat(diet): add recharts dep + placeholder log.json"
```

---

## Task 8.2: HPasaneel — DietCharts client component

**Files:**
- Create: `C:/code/HPasaneel/app/diet/DietCharts.tsx` (client)
- Create: `C:/code/HPasaneel/app/diet/page.tsx` (server)

- [ ] **Step 1: DietCharts.tsx (client)**

```tsx
"use client";

import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export interface DayRecord {
  date: string;
  steps: number;
  distance_km: number;
  exercise_kcal: number;
  weight_kg: number;
}

export default function DietCharts({ days }: { days: DayRecord[] }) {
  const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <div className="space-y-12">
      <section>
        <h2 className="text-2xl">体重推移</h2>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={sorted}>
            <XAxis dataKey="date" />
            <YAxis domain={["dataMin - 1", "dataMax + 1"]} />
            <Tooltip />
            <Line type="monotone" dataKey="weight_kg" stroke="#8884d8" />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section>
        <h2 className="text-2xl">歩数</h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={sorted}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="steps" fill="#82ca9d" />
          </BarChart>
        </ResponsiveContainer>
      </section>
      <section>
        <h2 className="text-2xl">運動消費 kcal</h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={sorted}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="exercise_kcal" fill="#ffc658" />
          </BarChart>
        </ResponsiveContainer>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: page.tsx (server)**

```tsx
import log from "../../content/diet/log.json";
import DietCharts, { DayRecord } from "./DietCharts";

export default function DietPage() {
  const days = log.days as DayRecord[];
  return (
    <main className="prose mx-auto p-8">
      <h1>Diet Dashboard</h1>
      <p className="text-sm text-gray-500">最終更新: {log.updated_at}</p>
      <DietCharts days={days} />
    </main>
  );
}
```

- [ ] **Step 3: dev / lint / build 確認**

```bash
npm run lint
npm run build
npm run dev
# ブラウザで http://localhost:3000/diet を開いて空 dashboard 表示確認
```

- [ ] **Step 4: Commit (HPasaneel 側)**

```bash
git add app/diet/
git commit -m "feat(diet): dashboard page with recharts (client) + server wrapper"
```

---

## Task 8.3: HPasaneel — メインナビに Diet 追加

**Files:** Modify `C:/code/HPasaneel/app/layout.tsx`

- [ ] **Step 1: 既存 layout.tsx を Read**

```bash
cat C:/code/HPasaneel/app/layout.tsx
```

ナビ配列の構造を確認（例: `const navItems = [{ href: "/company", label: "Company" }, ...]` のような形）。

- [ ] **Step 2: ナビに Diet 追加**

ナビ配列に `{ href: "/diet", label: "Diet" }` を末尾に追加。既存スタイル・コンポーネントを踏襲（独自スタイル追加禁止）。

- [ ] **Step 3: lint + build 確認**

```bash
cd C:/code/HPasaneel
npm run lint && npm run build
```
Expected: 既存 lint baseline と同等。

- [ ] **Step 4: 動作確認**

```bash
npm run dev
# ナビに "Diet" 項目が出ること、クリックで /diet に遷移すること
```

- [ ] **Step 5: Commit**

```bash
git add app/layout.tsx
git commit -m "feat(diet): add Diet link to main navigation"
```

---

# Phase 9: エッジケース統合テスト (§11)

## Task 9.1: Fitbit sync 失敗オフライン耐性

**Files:** Create `tests/test_edgecases.py`

- [ ] **Step 1-5: TDD**

```python
def test_orchestrator_continues_when_sync_fails(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config, Token, save_token_atomic, upsert_daily_weight, get_events_for_date, insert_intake_event
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", str(tmp_path / "hp"), "content/diet", "marginal", 2000))
    save_token_atomic(conn, Token("A","R", datetime(2030,1,1), "UID"))
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch("diet.cli_helpers.run_sync_async", side_effect=Exception("network down"))
    mocker.patch("click.prompt", return_value="=2300")
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    # sync 失敗でも食事は記録された
    events = get_events_for_date(conn, target)
    assert len(events) == 1
    assert events[0].kcal == 2300
```

`git commit -m "test(edgecase): sync failure tolerance"`

---

## Task 9.2: 体重 fallback (N 日前を使う + 警告)

- [ ] **Step 1-5: TDD**

```python
def test_weight_fallback_displays_days_ago(tmp_path, monkeypatch, mocker, capsys):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config, Token, save_token_atomic, upsert_daily_activity, upsert_daily_weight
    from datetime import date, datetime, timedelta
    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", "marginal", 2000))
    save_token_atomic(conn, Token("A","R", datetime(2030,1,1), "UID"))
    upsert_daily_activity(conn, target, 8000, 5.0, 250, 300)
    # 体重は 3 日前のみ
    upsert_daily_weight(conn, target - timedelta(days=3), 71.5)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", return_value="=2000")
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    captured = capsys.readouterr()
    assert "71.5" in captured.out
    assert "2026-05-22" in captured.out  # 計測日表示
```

`git commit -m "test(edgecase): weight fallback to last on-or-before with date display"`

---

## Task 9.3: diet not initialized guard

- [ ] **Step 1-5: TDD**

```python
def test_diet_command_requires_init(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "init" in result.output.lower()
```

`git commit -m "test(edgecase): diet init required guard"`

---

## Task 9.4: 同日複数回 publish (rev N suffix)

**Files:** Modify `src/diet/publish.py`, Modify tests/test_publish_git.py

- [ ] **Step 1-5: TDD**

```python
def test_same_day_republish_rev_n_suffix(tmp_path):
    import subprocess
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    rec2 = PublicDayRecord(date=date(2026, 5, 25), steps=2, distance_km=2.0, exercise_kcal=2, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [rec2], do_push=False)
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, check=True, capture_output=True, text=True)
    lines = log.stdout.splitlines()
    # 最新 commit (1 行目) が "rev 2" 等を含む
    assert any("rev 2" in l for l in lines[:2]) or any("(rev" in l for l in lines[:2])
```

実装方針: `publish_to_hpasaneel` が `git log --grep "diet: 2026-05-25"` で過去同日の commit 数を数えて N+1 を rev に。

`git commit -m "feat(publish): rev N suffix for same-day re-publishes"`

---

## Task 9.5: 429 rate limit

- [ ] **Step 1-5: TDD** (Task 4.3 で実装済み。エッジテストとして再確認)

```python
async def test_429_reset_seconds_in_state(httpx_mock):
    from diet.fitbit_client import FitbitClient
    import pytest, httpx
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        status_code=429, headers={"Fitbit-Rate-Limit-Reset": "600"}, json={},
    )
    client = FitbitClient(access_token="A")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_activity_summary("2026-05-25")
    assert client.rate_limit.reset_seconds == 600
```

`git commit -m "test(edgecase): 429 reset_seconds propagation"`

---

## Task 9.6: 並列 token refresh (process lock proof)

- [ ] **Step 1-5: TDD**

```python
def test_concurrent_token_writes_dont_corrupt(tmp_path):
    """並列 2 スレッドで save_token_atomic を 10 回ずつ呼ぶ → 最終状態が壊れない"""
    import threading
    from diet.db import open_db, save_token_atomic, load_token, Token
    from datetime import datetime
    db_path = tmp_path / "t.db"
    open_db(db_path).close()
    errors = []
    def worker(prefix):
        try:
            conn = open_db(db_path)
            for i in range(10):
                save_token_atomic(conn, Token(f"{prefix}{i}", f"R{prefix}{i}", datetime(2030,1,1), "U"))
        except Exception as e:
            errors.append(e)
    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert errors == [], f"concurrent writes corrupted: {errors}"
    # 最終状態は単一行
    conn = open_db(db_path)
    n = conn.execute("SELECT COUNT(*) FROM fitbit_token").fetchone()[0]
    assert n == 1
    tok = load_token(conn)
    assert tok.access_token.startswith(("a", "b"))
```

`git commit -m "test(edgecase): concurrent token rotation safety"`

---

## Task 9.7: cold start (記録なし + baseline なし)

- [ ] **Step 1-5: TDD**

```python
def test_cold_start_unconfirmed():
    from datetime import date
    from diet.intake import past_avg, decide_intake_kcal
    avg, n = past_avg({}, target_date=date(2026, 5, 25))
    d = decide_intake_kcal([], avg, n, bootstrap_baseline=None)
    assert d.label == "unconfirmed"
    assert d.intake_kcal is None
```

`git commit -m "test(edgecase): cold-start unconfirmed path"`

---

## Task 9.8: dirty HPasaneel repo (他に未コミット変更あり)

- [ ] **Step 1-5: TDD**

```python
def test_publish_with_other_uncommitted_changes(tmp_path):
    """log.json 以外に未コミット変更がある時、log.json だけ commit する（巻き込まない）

    pretrack: README.md を最初の commit に含める → 後で modify → publish 後も
    unstaged のままで、最後の commit に含まれないこと"""
    import subprocess
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)  # _init_repo は README.md を既に commit 済みにする想定 (Task 5.6 の helper)
    # README.md を tracked な状態で modify
    (repo / "README.md").write_text("# changed by user after init")
    # 未 stage であることを確認
    pre_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True)
    assert " M README.md" in pre_status.stdout, f"setup: README must be modified but unstaged, got: {pre_status.stdout!r}"

    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0)
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)

    # README.md は依然として未 stage の modified 状態
    post_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True)
    assert " M README.md" in post_status.stdout, f"README must remain unstaged, got: {post_status.stdout!r}"

    # 最後の commit に含まれるファイルは content/diet/log.json のみ
    files_in_last = subprocess.run(
        ["git", "show", "--name-only", "--pretty=", "HEAD"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip().splitlines()
    assert files_in_last == ["content/diet/log.json"], f"last commit must contain only log.json, got: {files_in_last}"
```

`git commit -m "test(edgecase): publish does not pull in unrelated dirty files"`

---

## Task 9.9: git push failure → CLI でユーザーに手動解決を促す

- [ ] **Step 1-5: TDD (publish 層と CLI 層 両方をカバー)**

```python
# (a) publish 層: CalledProcessError を伝播
def test_publish_propagates_push_failure(tmp_path, mocker):
    import subprocess
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec = PublicDayRecord(date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0)
    orig = subprocess.run
    def fake(args, **kw):
        if isinstance(args, list) and args[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(1, args, output=b"", stderr=b"non-fast-forward")
        return orig(args, **kw)
    mocker.patch("subprocess.run", side_effect=fake)
    import pytest
    with pytest.raises(subprocess.CalledProcessError):
        publish_to_hpasaneel(repo, "content/diet", [rec], do_push=True)

# (b) orchestrator 層: push 失敗時に手動解決メッセージを出すこと
def test_orchestrator_push_failure_shows_manual_resolution_message(tmp_path, monkeypatch, mocker, capsys):
    """publish が CalledProcessError を投げた時、orchestrator が click.echo で
    「手動で git push を解決してください」相当のメッセージを表示すること"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    import subprocess
    from diet.db import open_db, Config, save_config, Token, save_token_atomic, upsert_daily_activity, upsert_daily_weight
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", str(tmp_path / "hp"), "content/diet", "marginal", 2000))
    save_token_atomic(conn, Token("A","R", datetime(2030,1,1), "UID"))
    upsert_daily_activity(conn, target, 8000, 5.0, 250, 300)
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", return_value="=2300")
    mocker.patch("click.confirm", return_value=True)  # publish に進む
    mocker.patch("diet.publish.publish_to_hpasaneel",
                 side_effect=subprocess.CalledProcessError(1, ["git", "push"], stderr=b"non-fast-forward"))
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    out = capsys.readouterr().out
    assert "手動" in out or "manually" in out.lower() or "pull --rebase" in out
```

実装側: orchestrator の publish 呼び出しを try/except でくるみ、CalledProcessError を catch して `click.echo("publish 失敗: 手動で `git pull --rebase` してから再実行してください")` を表示、exit はしない（次回 `diet` 実行時に再試行できる）。

`git commit -m "feat(orchestrator)+test(edgecase): push failure shows manual resolution"`

---

## Task 9.10: cert 有効期間 + diet auth --regen-cert

- [ ] **Step 1-5: TDD (3 段: 有効期間検証 + idempotent 確認 + CLI 層)**

```python
def test_cert_validity_period(tmp_path):
    """生成した cert の not_valid_after が指定日数後であること"""
    from diet.oauth import generate_self_signed_cert
    from cryptography import x509
    from datetime import datetime, timezone, timedelta
    cert_path = tmp_path / "c.pem"
    key_path = tmp_path / "k.pem"
    generate_self_signed_cert(cert_path, key_path, "localhost", days_valid=3650)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    expected = datetime.now(timezone.utc) + timedelta(days=3650)
    delta = abs((cert.not_valid_after_utc - expected).total_seconds())
    assert delta < 60  # 生成タイミングのズレ許容

def test_generate_idempotent_when_both_exist(tmp_path):
    """既存ファイルがあれば上書きしない (no-op)"""
    from diet.oauth import generate_self_signed_cert
    cert_path = tmp_path / "c.pem"
    key_path = tmp_path / "k.pem"
    generate_self_signed_cert(cert_path, key_path, "localhost", 3650)
    original_cert = cert_path.read_bytes()
    generate_self_signed_cert(cert_path, key_path, "localhost", 3650)
    assert cert_path.read_bytes() == original_cert  # idempotent

def test_cli_auth_regen_cert_replaces_files(tmp_path, monkeypatch, mocker):
    """`diet auth --regen-cert` で既存 cert/key を削除して再生成 → serial が変わる"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config
    from datetime import date
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    from diet.oauth import generate_self_signed_cert
    cert = tmp_path / "oauth_cert.pem"
    key = tmp_path / "oauth_key.pem"
    generate_self_signed_cert(cert, key, "localhost", 3650)
    original_bytes = cert.read_bytes()
    # OAuth フロー本体は mock (auth サブコマンドが run_init_flow を呼ぶことだけ確認したい)
    spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["auth", "--regen-cert"])
    assert result.exit_code == 0
    # cert は再生成され、内容が変わっている
    assert cert.exists()
    assert cert.read_bytes() != original_bytes
    spy.assert_called_once()
```

`git commit -m "test(edgecase): cert validity period + regen via CLI"`

---

## Task 9.11: crash recovery (token rotation 中の crash → diet auth 案内)

- [ ] **Step 1-5: TDD**

```python
async def test_refresh_failure_with_revoked_token_propagates(httpx_mock):
    """refresh エンドポイントが 400 (invalid_grant) を返す → 例外を上層で捕捉して
    diet auth 案内するハンドラを CLI に持つ"""
    from diet.oauth import refresh_access_token
    import httpx
    import pytest
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        status_code=400, json={"errors": [{"errorType": "invalid_grant"}]},
    )
    with pytest.raises(httpx.HTTPStatusError):
        await refresh_access_token("CID", "CSEC", "REVOKED_REFRESH")

def test_cli_sync_with_revoked_token_directs_to_auth(tmp_path, monkeypatch, mocker):
    """sync 中に refresh が失敗 → "diet auth" を案内するメッセージで exit 非 0"""
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import open_db, Config, save_config, Token, save_token_atomic
    from datetime import date, datetime
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(date(1979,12,1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None))
    save_token_atomic(conn, Token("A","R_REVOKED", datetime(2030,1,1), "UID"))
    import httpx
    mocker.patch("diet.cli_helpers.run_sync_async",
                 side_effect=httpx.HTTPStatusError("refresh failed", request=mocker.MagicMock(), response=mocker.MagicMock()))
    runner = CliRunner()
    result = runner.invoke(app, ["sync"])
    assert result.exit_code != 0
    assert "diet auth" in result.output
```

実装側: cli.py の sync ハンドラで refresh 例外を catch、`click.echo` で `"refresh token が無効になりました。`diet auth` で再認証してください"` を出し、exit non-zero。

`git commit -m "feat(cli)+test(edgecase): refresh failure directs user to diet auth"`

---

# Phase 10: 仕上げ

## Task 10.1: README

**Files:** Create `README.md`

- [ ] **Step 1: 内容**

```markdown
# Fitbit 連動ダイエット CLI

「食べた分だけ歩く・走る」を運用する個人用ダイエットツール。

## セットアップ

### 1. Fitbit Developer App 登録 (1 回のみ)

`https://dev.fitbit.com/apps` で以下を入力:
(spec § 8.1 の表を流用)

### 2. Renpho → Fitbit 同期 (1 回のみ)

Renpho アプリ → 設定 → サードパーティ連携 → Fitbit。

### 3. プロジェクト install

\`\`\`bash
git clone <repo>
cd fitbit連動ダイエット
cp .env.example .env
# .env を編集して FITBIT_CLIENT_ID/SECRET を入れる
uv tool install .
\`\`\`

### 4. 初回セットアップ

\`\`\`bash
diet init
\`\`\`

### 5. キャリブレーション

\`\`\`bash
diet calibrate
\`\`\`

## 日次運用

\`\`\`bash
diet
\`\`\`

## CLI コマンド一覧

(spec § 9 の表を流用)
```

- [ ] **Step 2: Commit**

`git add README.md && git commit -m "docs: README with setup and command reference"`

---

## Task 10.2: 手動 E2E スモーク

- [ ] **Step 1**: 実 Fitbit dev portal で app 登録 (Callback URL = `https://localhost:8765/callback`)
- [ ] **Step 2**: `.env` に実 Client ID/Secret 記入
- [ ] **Step 3**: `uv tool install .`
- [ ] **Step 4**: `diet init` (生年月日 1979-12-01 等を入力)、ブラウザ警告を Proceed して認証完了
- [ ] **Step 5**: `diet calibrate` で `marginal` 確定
- [ ] **Step 6**: `diet` で `=2300` 入力、収支表示確認、`y` で publish
- [ ] **Step 7**: HPasaneel 側で `git log` を確認、Cloudflare Pages deploy 待ち、`/diet` ページで表示確認

---

## Plan Review Loop

After this plan is reviewed by codex:
- If issues: fix and re-dispatch
- If approved: proceed to subagent-driven-development

---

## Execution Handoff

Per user global rule: subagent-driven (option 1) is default. After plan approval:
- Use `superpowers:subagent-driven-development` skill
- Fresh subagent per task, two-stage review between tasks
- ~45 tasks total (Phase 0..10)
