# Fitbit 連動ダイエット CLI

「食べた分だけ歩く・走る」をパーソナル運用するための CLI。**Google Health API v4** で取得した運動・体重データに、CLI で手入力した食事カロリーを突き合わせて毎日の収支を算出し、運動・体重のみを HPasaneel ダッシュボードに公開する。

> **2026-06: Fitbit Web API → Google Health API に移行しました。** OAuth は標準 Google OAuth 2.0（自己署名 TLS 証明書は不要）。運動消費は `active-energy-burned`（基礎代謝フリー）固定。既存ユーザーの移行手順は下記「既存環境からの移行」を参照。

- 食事カロリー数値・メニュー名は **絶対に公開しない**（公開境界の物理分離を `tests/test_publish_boundary.py` で担保）
- 公開対象は steps / distance / exercise_kcal / weight のみ

設計の詳細は [`docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`](docs/superpowers/specs/2026-05-25-fitbit-diet-design.md)、実装計画は [`docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md`](docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md) を参照。

---

## セットアップ

### 1. Google Cloud Console での OAuth クライアント登録（ユーザー手動・1 回のみ）

`https://console.cloud.google.com` で以下を順に実施:

1. **プロジェクトを作成**（例 `personal-diet-cli`）。
2. **Google Health API を有効化**（「API とサービス」→「ライブラリ」で検索して有効化）。
3. **OAuth 同意画面を設定**（User Type: External）:
   - **公開ステータスは必ず「本番環境（Production）」に発行**する。Testing のままだと **refresh token が 7 日で失効** し毎週認証し直す羽目になる。
   - **テストユーザーに自分の Gmail（`pcjidouka@gmail.com`）を追加**。
   - 単一ユーザー利用（< 100 ユーザー上限）なので第三者セキュリティレビューは不要。
   - scope（read-only）2 つ:
     - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
     - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
4. **OAuth クライアント ID を作成**:
   - **アプリケーションの種類: ウェブアプリケーション（Web application）**。
   - **承認済みのリダイレクト URI に `http://localhost:8765/callback` を登録**（Google は localhost を HTTPS-only ルールから除外するので PLAIN HTTP で良い。証明書は不要）。

作成後に表示される **クライアント ID** と **クライアント シークレット** をプロジェクトルートの `.env` に保存（`.env.example` 参照）:

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8765/callback
```

### 2. Renpho → Fitbit → Google Health 体重同期設定（ユーザー手動・1 回のみ）

- Renpho アプリ → 設定 → サードパーティ連携 → Fitbit を選択して認可
- 以降、Renpho 計測のたびに Fitbit 側 `body/weight` に流れ、さらに Google Health の `weight` に同期される（想定。この多段経路は live で要確認）
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

プロンプトに従って生年月日・身長・性別・タイムゾーン・HPasaneel リポジトリパスを入力。ブラウザが立ち上がって Google OAuth に進むので、Google アカウントで認可する。**PLAIN HTTP の loopback callback** なので証明書の警告ステップは無い（許可を押すだけ）。認証後、続けて過去 30 日分の初回 sync が走る。

### 5. `diet calibrate`（情報表示のみ）

```bash
diet calibrate
```

過去 N 日（デフォルト 14 日）の活動カロリー（`active_energy` / `total_calories`）を並べて表示するだけのコマンド。運動消費は常に `active_energy`（基礎代謝を除いた活動由来の消費）を使い、`total_calories`（基礎代謝込み）は参考値で収支には使わない。設定変更や選択プロンプトは無い。

---

## 既存環境からの移行（Fitbit → Google Health）

旧 Fitbit 版から使っている場合、初回起動時に DB が v1→v2 へ自動 migration される（`daily_activity` のカロリー列リネーム等）。ただし **旧 Fitbit の OAuth token は Google に転用できないため自動的に破棄される**。

1. 上記「セットアップ 1」に従って Google Cloud Console で OAuth クライアントを登録し、`.env` を `GOOGLE_*` キーに置き換える（旧 `FITBIT_*` キーは不要）。
2. `diet auth` を実行して Google アカウントで再認証（再同意）する。
3. 以降は通常どおり `diet` / `diet sync` が使える。

蓄積済みの食事記録・歩数・体重などの DB データはそのまま保持される。

---

## CLI コマンド一覧

| コマンド | 役割 |
|---|---|
| `diet` | 1 日分の対話フロー（Google Health sync → 食事入力 → 収支 → publish） |
| `diet init` | 初期セットアップ（profile + Google OAuth + 初回 sync） |
| `diet sync` | Google Health sync のみ実行（対話なし、cron 用） |
| `diet calibrate` | 直近 N 日の活動カロリーを表示（情報表示のみ。`--days` 指定可） |
| `diet weight 71.2` | 体重を手動入力（Renpho 同期不全時の fallback、`--date` 指定可） |
| `diet baseline 2200` | `bootstrap_daily_kcal` を更新（cold start 期の見直し用） |
| `diet show [--date YYYY-MM-DD]` | 指定日の収支を表示のみ（食事入力・publish なし） |
| `diet auth` | Google OAuth token を再取得（refresh 完全失敗時の復旧。`--port` で代替ポート指定可） |
| `diet serve` | ローカル Web UI を `127.0.0.1` で起動（自宅 PC 専用。`--port` 既定 8770） |

`diet` と `diet show` は `--date 2026-05-23` で過去日も対象にできる。

---

## 日常運用例

```bash
# 朝起きて昨日分を締める
$ diet --date 2026-05-24
[1/5 sync]   Google Health 取得中... done (steps=9821, exercise_kcal=420)
[2/5 食事]   昨日食べたもの: ラーメン 1200, 唐揚げ定食 900
[3/5 体重]   71.4 kg (Renpho 同期済み)
[4/5 収支]   摂取 2100 - (BMR 1620 + 運動 420) = +60 kcal
[5/5 公開]   HPasaneel に運動・体重のみ公開しますか? [y/N]: y
→ log.json 更新 → git commit & push 完了
```

---

## ローカル Web UI（`diet serve`）

CLI の毎日フローをブラウザで完結させたい場合は、自宅 PC でローカル Web サーバーを起動する。

```bash
diet serve            # http://127.0.0.1:8770 を起動（Ctrl+C で停止）
diet serve --port 9000
```

ブラウザで `http://127.0.0.1:8770` を開くと、当日の歩数・距離・運動 kcal・体重・BMR・食事累積・収支が一画面に表示される。同期ボタン → 食事入力（`+追加` / `=上書き`）→ 体重入力 → 「HPasaneel に運動・体重のみ公開」までブラウザで完了でき、過去 30 日の体重・歩数グラフ（Chart.js、ローカル同梱・CDN 非依存）も表示される。CLI（`diet`）は従来どおり併存する。

**設計上の制約（v1）**:
- **`127.0.0.1` バインド固定**（外部公開不可）。特権ポート（80/443）は非対応で `--port` は 1024–65535。
- 食事 kcal・メニュー名は **localhost のブラウザにのみ**返り、publish には一切出ない（CLI と同一の `build_records_from_db` 5 フィールド allowlist を経由）。
- 悪意あるサイトからの localhost アクセス（DNS rebinding 等）対策として **Host 検証・mutation 時 Origin チェック・起動毎 CSRF トークン・loopback 強制**を実施。食事ノート等は `textContent` で描画（stored XSS 防止）。
- **OAuth（`diet auth`）は v1 では CLI 据え置き**。token 失効・不在時は UI が「CLI で `diet auth` を実行」と促す。

設計の詳細は [`docs/superpowers/specs/2026-06-03-local-web-ui-design.md`](docs/superpowers/specs/2026-06-03-local-web-ui-design.md)、実装計画は [`docs/superpowers/plans/2026-06-03-local-web-ui.md`](docs/superpowers/plans/2026-06-03-local-web-ui.md) を参照。

---

## アーキテクチャ

- **言語 / ランタイム**: Python 3.11+, `uv` で依存管理
- **ストレージ**: SQLite (`data/diet.db`)、`intake_events` / `daily_activity` / `daily_weight` / `config` / `fitbit_token`（OAuth token 格納。歴史的名称を保持）の 5 テーブル。`daily_activity` は `active_energy_kcal`（収支に使う、BMR フリー）と `total_calories_kcal`（診断用、BMR 込み）を保持
- **Google Health 連携**: 標準 Google OAuth 2.0、PLAIN HTTP の loopback callback サーバー（`http://localhost:8765/callback`、証明書不要）。API base は `https://health.googleapis.com/v4`、日次データは `dataPoints:dailyRollUp`、体重は `weight` data type
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

# テスト実行（211 tests）
uv run pytest

# 個別テスト
uv run pytest tests/test_publish_boundary.py -v
```

実装計画と Task 分割は [`docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md`](docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md) を参照。設計書は [`docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`](docs/superpowers/specs/2026-05-25-fitbit-diet-design.md)。
