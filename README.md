# Fitbit 連動ダイエット CLI

「食べた分だけ歩く・走る」をパーソナル運用するための CLI。Fitbit Web API で取得した運動・体重データに、CLI で手入力した食事カロリーを突き合わせて毎日の収支を算出し、運動・体重のみを HPasaneel ダッシュボードに公開する。

- 食事カロリー数値・メニュー名は **絶対に公開しない**（公開境界の物理分離を `tests/test_publish_boundary.py` で担保）
- 公開対象は steps / distance / exercise_kcal / weight のみ

設計の詳細は [`docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`](docs/superpowers/specs/2026-05-25-fitbit-diet-design.md)、実装計画は [`docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md`](docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md) を参照。

---

## セットアップ

### 1. Fitbit Developer App 登録（ユーザー手動・1 回のみ）

`https://dev.fitbit.com/apps` で "Register a new application" から以下を入力:

| フィールド | 値 | 備考 |
|---|---|---|
| Application Name | `Personal Diet CLI` 等 | 任意 |
| Description | `Personal use diet tracking via Fitbit activity and weight data` | 任意 |
| Application Website | 任意の HTTPS URL（自分の GitHub 等）| HTTPS 必須 |
| Organization | 自分の名前 | 個人なので任意 |
| Organization Website | 同上 | HTTPS 必須 |
| Terms of Service URL | 同上 | HTTPS 必須 |
| Privacy Policy URL | 同上 | HTTPS 必須 |
| **OAuth 2.0 Application Type** | **Personal** | これ以外は審査必要 |
| **Callback URL** | **`https://localhost:8765/callback`** | Fitbit は HTTPS のみ受付 |
| **Default Access Type** | **Read-only** | 書き込みは使わない |

登録完了後、自分のアプリを開くと **Client ID** と **Client Secret** が表示される。プロジェクトルートに `.env` を作成して保存:

```
FITBIT_CLIENT_ID=23XXXX
FITBIT_CLIENT_SECRET=abc123def456...
FITBIT_REDIRECT_URI=https://localhost:8765/callback
```

### 2. Renpho → Fitbit 同期設定（ユーザー手動・1 回のみ）

- Renpho アプリ → 設定 → サードパーティ連携 → Fitbit を選択して認可
- 以降、Renpho 計測のたびに自動で Fitbit 側 `body/weight` に流れる
- 同期不全時は `diet weight 71.2` で手動入力可能

### 3. インストール

グローバルインストール（推奨）:

```bash
uv tool install .
```

開発時に使うなら `uv run diet ...` で都度実行でも可。

### 4. 初回 `diet init`

```bash
diet init
```

プロンプトに従って生年月日・身長・性別・タイムゾーン・HPasaneel リポジトリパスを入力。自己署名 TLS 証明書が生成され、ブラウザが立ち上がって Fitbit OAuth に進む。初回のみ「Advanced → Proceed to localhost (unsafe)」で証明書警告を進めば認証完了。続けて過去 30 日分の初回 sync が走る。

### 5. `diet calibrate` で exercise_calorie_source を決定

```bash
diet calibrate
```

過去 14 日の Fitbit カロリー候補（`logged_activities` / `marginal`）を並べて表示するので、どちらを `exercise_kcal` の正式値として使うか選ぶ。確定するまでは `marginal` がデフォルト。

---

## CLI コマンド一覧

| コマンド | 役割 |
|---|---|
| `diet` | 1 日分の対話フロー（Fitbit sync → 食事入力 → 収支 → publish） |
| `diet init` | 初期セットアップ（profile + OAuth + 初回 sync） |
| `diet sync` | Fitbit sync のみ実行（対話なし、cron 用） |
| `diet calibrate` | Fitbit カロリー候補を並べて `exercise_calorie_source` を決定 |
| `diet weight 71.2` | 体重を手動入力（Renpho 同期不全時の fallback、`--date` 指定可） |
| `diet baseline 2200` | `bootstrap_daily_kcal` を更新（cold start 期の見直し用） |
| `diet show [--date YYYY-MM-DD]` | 指定日の収支を表示のみ（食事入力・publish なし） |
| `diet auth` | OAuth token を再取得（refresh 完全失敗時の復旧、`--regen-cert` で証明書も再生成） |

`diet` と `diet show` は `--date 2026-05-23` で過去日も対象にできる。

---

## 日常運用例

```bash
# 朝起きて昨日分を締める
$ diet --date 2026-05-24
[1/5 sync]   Fitbit 取得中... done (steps=9821, exercise_kcal=420)
[2/5 食事]   昨日食べたもの: ラーメン 1200, 唐揚げ定食 900
[3/5 体重]   71.4 kg (Renpho 同期済み)
[4/5 収支]   摂取 2100 - (BMR 1620 + 運動 420) = +60 kcal
[5/5 公開]   HPasaneel に運動・体重のみ公開しますか? [y/N]: y
→ log.json 更新 → git commit & push 完了
```

---

## アーキテクチャ

- **言語 / ランタイム**: Python 3.11+, `uv` で依存管理
- **ストレージ**: SQLite (`data/diet.db`)、`intake_events` / `daily_activity` / `daily_weight` / `config` / `oauth_token` の 5 テーブル
- **Fitbit 連携**: OAuth 2.0 PKCE フロー、自己署名 TLS 証明書付きローカル callback サーバー（`https://localhost:8765/callback`）
- **公開**: HPasaneel リポジトリの `content/diet/log.json` に運動・体重のみ書き出し → git commit & push
- **プライバシー境界**: publish 関数は `daily_activity` と `daily_weight` のみ SELECT、`intake_events` には構造的に触らない（`tests/test_publish_boundary.py` で `note` 文字列が log.json に一切現れないことを diff 検証）

詳細な設計判断・データフロー・エッジケースは [`docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`](docs/superpowers/specs/2026-05-25-fitbit-diet-design.md) に記載。

---

## プライバシー境界

| 項目 | 公開 | 理由 |
|---|---|---|
| `intake_events.note`（メニュー名） | **絶対秘匿** | 食生活・嗜好は人格情報 |
| `intake_events.kcal`（摂取カロリー） | dashboard 非公開 | 出さないが運動 + 体重変動から逆算され得るのは許容 |
| steps / distance / exercise_kcal / weight | **HPasaneel に公開** | 「見られている」プレッシャーをダイエット動機に活用 |

公開境界は allowlist 2 層 + ユニットテストで担保しており、`intake_events` に触る publish コードはレビューで弾く。

---

## 開発

```bash
# 依存セットアップ
uv sync

# テスト実行（159 tests）
uv run pytest

# 個別テスト
uv run pytest tests/test_publish_boundary.py -v
```

実装計画と Task 分割は [`docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md`](docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md) を参照。設計書は [`docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`](docs/superpowers/specs/2026-05-25-fitbit-diet-design.md)。
