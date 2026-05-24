# Fitbit 連動ダイエット CLI — 設計書

- 作成日: 2026-05-25
- 最終更新: 2026-05-25（codex review 反映, rev 2）
- ステータス: ユーザーレビュー待ち
- スコープ: 2 リポジトリ横断
  - `C:/code/fitbit連動ダイエット` — Python CLI（本リポジトリ）
  - `C:/code/HPasaneel` — Next.js ダッシュボードページ追加

---

## 1. 目的と方針

「食べた分だけ歩く・走る」をパーソナル運用するための CLI ツールを作る。

- **食事カロリー**: CLI で手入力（内部のみ、絶対公開しない）
- **運動データ・体重**: Fitbit Web API 経由で取得
- **基礎代謝（BMR）**: 生年月日・身長・性別と当日体重から自動算出
- **収支**: 摂取 vs (BMR + 運動消費) を毎回算出
- **公開**: 運動データと体重のみを HPasaneel に日次でダッシュボード公開

「見られている」プレッシャーをダイエットの動機付けに使うが、食事カロリーから収支まで逆算されないよう、**食事系は構造的に絶対公開しない境界**を設計に組み込む。

---

## 2. ユーザープロファイル（固定値）

| 項目 | 値 |
|---|---|
| 生年月日 | 1979-12-01 |
| 身長 | 169 cm |
| 性別 | male |
| タイムゾーン | Asia/Tokyo |

年齢は実行時に「対象日 (Asia/Tokyo) と生年月日の差」から算出。UTC や `datetime.now()` の素の値は使わない。

---

## 3. BMR 計算式

ミフリン-セントジョー式（医療現場の標準、現代人での精度がハリス・ベネディクト式より高い）。

```
男性 BMR = 10 × 体重(kg) + 6.25 × 身長(cm) − 5 × 年齢 + 5
```

このプロファイルでは:
```
BMR = 10 × 体重 + 6.25 × 169 − 5 × 年齢 + 5
    = 10 × 体重 + 836.25 − 5 × (年齢 − 0)
```
例: 体重 70kg, 年齢 46 歳 → 700 + 1056.25 − 230 + 5 = 1531 kcal/日

**重要:**
- **年齢は対象日 (Asia/Tokyo) 基準**。`bmr(target_date, body_weight, birthday, height)` のような純粋関数で実装し、内部で対象日を Asia/Tokyo 解釈して差分を計算する
- **体重は対象日に最も近い「対象日以前」の値を使う**。Renpho の遅延同期で対象日より後の体重を将来計算した時は除外する（タイムマシン禁止）
- 体重と年齢が毎日変動し得るため、テーブルに保存せず実行時に毎回再計算する

---

## 4. データソースとフロー

```
[Renpho 体重計] ──BLE──▶ [Renpho アプリ] ──公式連携──▶ [Fitbit body/weight]
[Fitbit デバイス] ──BLE──▶ [Fitbit アプリ] ──────────────▶ [Fitbit activities]
                                                                │
                                                                ▼
                                                       [Fitbit Web API]
                                                                │
                                                                ▼
[CLI: diet コマンド] ◀── 食事 kcal 手入力 ── ユーザー
       │
       ├─ SQLite (data/diet.db) に全データ保存
       ├─ 収支算出（BMR + 運動消費 vs 食事）
       └─ HPasaneel/content/diet/log.json に運動・体重のみ書き出し → git commit & push
```

**重要な仕様 — Fitbit カロリーの取り扱い（codex 指摘の HIGH 対応）:**

Fitbit デバイスは 24 時間装着しない前提のため、Fitbit が出す TDEE（基礎代謝込み消費）は使えない。さらに **Fitbit の `summary.activityCalories` は名前に反して基礎代謝を含む** ので、これも使わない。BMR 二重計上の罠を避ける。

採用候補（優先順）:

1. **`activities[].calories`（明示的に記録された運動エントリの合計）** — 最も意味が明確。ただし「散歩」「掃除」などをユーザーが手で記録しない限り 0 になる
2. **`summary.marginalCalories`** — Fitbit の中で「基礎代謝を引いた、活動由来っぽい消費」に最も近い。装着していない時間が長いとノイズが乗る
3. **`summary.steps × 体重 × 係数` で独自算出** — 装着精度に依存しすぎる場合の fallback

**MVP は `activities[].calories` + `marginalCalories` の両方を取得して DB に保存**し、`diet calibrate` コマンド（§ 8）で数日分を並べて表示し、ユーザーがどれを `exercise_kcal` の正式値とするか判断する。判断後は config に `exercise_calorie_source` を保存して以降そちらを使う。

---

## 5. アーキテクチャ（B 案: 単一コマンド対話型）

`diet` 1 コマンドで 1 日分が完結する対話フロー:

```
$ diet
[1/5 Fitbit同期] 運動データ取得中...
    歩数 8,234 / 距離 5.3km
    運動消費 280kcal (source: activities[].calories)
    体重 71.2kg (Renpho→Fitbit経由、2026-05-25 計測)

[2/5 食事入力] 今日のカロリー (現在の累積: 1,800kcal)
    入力 (+追加 / =上書き / Enter=skip):
    > +500
    累積 2,300kcal

[3/5 基礎代謝] BMR (46歳/男性/169cm/71.2kg) = 1,543kcal

[4/5 収支] 摂取 2,300 vs 消費 (BMR 1,543 + 運動 280) = -477kcal (赤字)
    黒字化まで あと約 11,900歩 (または 走 3.4km)

[5/5 公開] HPasaneel に運動・体重のみ公開しますか? [y/N]: y
    → content/diet/log.json 更新 (2026-05-25 entry)
    → git: pull --rebase → stage → commit → push 完了
```

**ポイント:**
- 食事入力は **append（累積）** がデフォルト。`+500` で追加、`=2300` で上書き、Enter でスキップ
- 過去日修正は `diet --date 2026-05-23` で起動、全フローが過去日で動く（年齢・体重も対象日基準）
- Fitbit sync 失敗時は警告のみ出して食事入力に進む（オフライン耐性）
- 5 ステップは順に走り、ユーザー操作が必要なのは [2] 食事入力と [5] 公開可否のみ

---

## 6. データスキーマ（SQLite）

`data/diet.db` 1 ファイルで完結。`data/` ディレクトリは `.gitignore` 済み。

```sql
-- 設定（1 行のみ）
config (
  birthday               DATE,        -- '1979-12-01'
  height_cm              INTEGER,     -- 169
  sex                    TEXT,        -- 'male'
  timezone               TEXT,        -- 'Asia/Tokyo'
  hpasaneel_path         TEXT,        -- 'C:/code/HPasaneel'
  hpasaneel_diet_root    TEXT,        -- 'content/diet'
  exercise_calorie_source TEXT        -- 'logged_activities' | 'marginal' | 'steps_estimated'
                                      -- 初期は NULL、calibrate 後に確定
)

-- 食事イベント（1 回ごと append）  ← 内部のみ・絶対公開しない
intake_events (
  id            INTEGER PRIMARY KEY,
  date          DATE,        -- YYYY-MM-DD（Asia/Tokyo で正規化）
  timestamp     DATETIME,    -- 入力時刻
  kcal          INTEGER,
  op            TEXT,        -- 'append' or 'override'
  note          TEXT         -- 任意メモ
)

-- Fitbit 運動データ（日次）  ← 公開対象
daily_activity (
  date                       DATE PRIMARY KEY,
  steps                      INTEGER,
  distance_km                REAL,
  -- カロリー候補を全部保存（calibration 用に並列保持）
  logged_activities_kcal     INTEGER,  -- activities[].calories 合計
  marginal_kcal              INTEGER,  -- summary.marginalCalories
  -- 上記いずれかが exercise_kcal の正式値（exercise_calorie_source で選択）
  last_synced                DATETIME
)

-- 体重（Renpho→Fitbit 経由・日次）  ← 公開対象
daily_weight (
  date          DATE PRIMARY KEY,    -- 計測日（測定タイムスタンプを Asia/Tokyo で日付化）
  weight_kg     REAL,
  last_synced   DATETIME
)

-- Fitbit OAuth token（atomic 更新が必須）
fitbit_token (
  id             INTEGER PRIMARY KEY CHECK (id = 1),  -- 単一行を強制
  access_token   TEXT,
  refresh_token  TEXT,
  expires_at     DATETIME,
  user_id        TEXT,
  rotated_at     DATETIME
)
```

**設計判断:**
- **収支・BMR は保存しない** → 毎回算出（体重訂正で過去日が自動的に正しい値になる）
- **食事は append 履歴** → 全イベントを残し、`op='override'` も含めて履歴追跡可能
- **公開境界の物理分離（codex Medium-2 対応）** → § 7 で詳述。publish 関数は `daily_activity` と `daily_weight` のみ SELECT し、`intake_events` に触らないことをユニットテストで担保
- **time zone は Asia/Tokyo 固定** → 日付境界は JST の 0 時
- **Fitbit カロリー候補を 2 列で保存（codex HIGH 対応）** → calibration 期間中も後追いでも比較可能

---

## 7. 公開仕様（HPasaneel 連動）

### 書き出しファイル

`<hpasaneel_path>/<hpasaneel_diet_root>/log.json` 1 ファイルに累積。

```json
{
  "updated_at": "2026-05-25T22:34:12+09:00",
  "days": [
    {
      "date": "2026-05-25",
      "steps": 8234,
      "distance_km": 5.3,
      "exercise_kcal": 280,
      "weight_kg": 71.2
    },
    {
      "date": "2026-05-24",
      "steps": 12100,
      "distance_km": 7.8,
      "exercise_kcal": 420,
      "weight_kg": 71.5
    }
  ]
}
```

**公開フィールドの allowlist 2 層防衛（codex Medium-2 対応）:**

1. **typed DTO 層** — `publish.py` 内で `@dataclass class PublicDayRecord` を定義し、`date / steps / distance_km / exercise_kcal / weight_kg` のみフィールドに持たせる。DB から DTO への変換は明示的にこの 5 フィールドだけを SELECT して詰める
2. **JSON schema guard 層** — `log.json` 書き出し直前に `jsonschema` でバリデーション。`additionalProperties: false`、`required: [date, steps, distance_km, exercise_kcal, weight_kg]` で他フィールドが混入したら例外で停止

`updated_at` はトップレベル 1 個のみ、JSON 全体が「最終生成時刻」を持つ。これは公開して問題ない情報と判断（ユーザー本人の公開意図）。

**git 履歴の不可逆性:** 一度 push した体重等は git history に永久に残る。ロールバックしたければ push 前の段階で訂正する。push 後の訂正は新 commit になり、過去 commit には残り続けることをユーザーは認識しておく。

### git 連携 — 安全な実行シーケンス（codex Low-2 対応）

```bash
cd <hpasaneel_path>
git status --porcelain content/diet/log.json    # log.json に手動変更が無いか確認
# 手動変更があれば対話で「上書きしますか? [y/N]」、no なら publish 中止
git pull --rebase                                # リモートとの差分取り込み
# diet コマンドが log.json を再生成（pull で取れた最新内容に merge する形）
# stage は log.json のみ限定指定
git add content/diet/log.json
git commit -m "diet: 2026-05-25 update"
git push          # → Cloudflare Pages auto deploy
```

- **HPasaneel に他の未コミット変更がある場合** → log.json 以外には触らない（`git add .` は禁止）。確認プロンプトを出す
- **`pull --rebase` 失敗** → 手動解決を促して終了
- **同じ日の再 publish** → log.json の該当 entry を上書き、commit メッセージは `diet: 2026-05-25 update (rev N)`

### HPasaneel 側ダッシュボードページ（本プロジェクトで一緒に実装）

- `app/diet/page.tsx` を新規追加
- `content/diet/log.json` を import（Next.js の静的ビルドで bundle に同梱）
- 体重推移グラフ・歩数バー・距離・運動消費の表示
- chart ライブラリ: `recharts`（軽量、SSR 互換）を新規依存に追加
- メインナビゲーション（Company / Research / ... と並列）に "Diet" 項目を追加

**MVP 縮退オプション（codex Scope 対応）**: 開発工数が逼迫した場合は `recharts` を一旦外して素の HTML table 表示でも MVP として出せる。ナビ追加は最後に回す。

---

## 8. 初回セットアップ + calibration

### 1. Fitbit Developer App 登録（ユーザー手動・1 回のみ）

- https://dev.fitbit.com で Personal アプリ登録（無料）
- リダイレクト URL: `http://localhost:8765/callback`
- 取得した Client ID / Client Secret を `.env` に保存

### 2. Renpho → Fitbit 同期設定（ユーザー手動・1 回のみ）

- Renpho アプリ → 設定 → サードパーティ連携 → Fitbit を選択して認可
- 以降、Renpho 計測のたびに自動で Fitbit 側 body/weight に流れる

### 3. `diet init`

```
$ diet init
生年月日 (YYYY-MM-DD): 1979-12-01
身長 (cm): 169
性別 (male/female): male
タイムゾーン [Asia/Tokyo]:
HPasaneel リポジトリパス [C:/code/HPasaneel]:
HPasaneel ダッシュボードルート [content/diet]:

→ data/diet.db 作成、config 保存
→ Fitbit OAuth フロー起動（ブラウザが開く）
→ http://localhost:8765/callback で token 受け取り → DB 保存
→ 初回 sync 実行（過去 30 日分を遡って取得、カロリー 2 候補を両方保存）
→ 「次に `diet calibrate` を実行して exercise_kcal の値を決めてください」と案内
```

### 4. `diet calibrate`（codex Scope 対応：新規追加コマンド）

過去 N 日（デフォルト 14 日）の Fitbit カロリー値を並べて表示し、ユーザーが「どのフィールドを `exercise_kcal` として採用するか」を決める:

```
$ diet calibrate
過去 14 日の Fitbit カロリー比較:

date         steps  距離km  logged_activities  marginal  装着時間
2026-05-25   8234    5.3    280                340       18h
2026-05-24  12100    7.8    420                550       21h
2026-05-23   3200    2.1     90                120       12h  ← 装着少
2026-05-22  14500    9.2    480                600       23h
...

各カロリー候補の意味:
  - logged_activities: ウォーキング・ランニング等を明示的に記録した分の合計
  - marginal:          Fitbit が「活動由来」と推定した分（基礎代謝込みではない）

どちらを exercise_kcal として採用しますか? [logged_activities/marginal/decide_later]:
> marginal
→ config.exercise_calorie_source = 'marginal' に保存
```

`decide_later` を選ぶと毎日両方表示しつつ収支は marginal で仮計算、`diet calibrate` でいつでも変更可能。

---

## 9. プロジェクト構成

```
C:/code/fitbit連動ダイエット/
  src/
    diet/
      __init__.py
      __main__.py        # diet コマンド本体（対話フロー orchestrator）
      cli.py             # click/typer 定義（diet / diet init / diet calibrate / diet auth）
      fitbit_client.py   # Fitbit Web API ラッパー + rate limit tracking
      oauth.py           # OAuth フロー + localhost callback server + atomic token rotation
      bmr.py             # BMR 計算（純粋関数、target_date 引数で過去日対応）
      db.py              # SQLite 接続・スキーマ管理
      publish.py         # log.json 生成 + git 操作（公開境界、DTO + JSON schema 2層）
      calibrate.py       # calibration コマンド
      formatters.py      # CLI 表示整形
  tests/
    test_bmr.py
    test_publish_boundary.py    # publish が intake_events に触らないことを担保
    test_publish_schema.py      # JSON schema guard の動作確認
    test_oauth_atomic.py        # token rotation 中の crash シミュレーション
    test_age_timezone.py        # 過去日 BMR 計算が Asia/Tokyo 基準であること
    ...
  data/                  # .gitignore
    diet.db
  .env                   # .gitignore（Client ID / Secret）
  .env.example
  pyproject.toml         # uv 管理
  README.md
  docs/superpowers/specs/
    2026-05-25-fitbit-diet-design.md  # この文書

C:/code/HPasaneel/
  app/diet/page.tsx      # 追加: ダッシュボードページ
  app/layout.tsx         # ナビに "Diet" 追加（既存ファイル編集）
  content/diet/log.json  # diet コマンドが書き出す
  package.json           # recharts 依存追加
```

---

## 10. 依存ライブラリ

### Python（`pyproject.toml`）

- `httpx` — Fitbit API HTTP クライアント
- `python-dotenv` — `.env` 読み込み
- `click` または `typer` — CLI フレームワーク
- `jsonschema` — 公開 JSON の schema guard
- 標準ライブラリ: `sqlite3`, `datetime`, `zoneinfo`, `http.server`, `subprocess`, `dataclasses`

パッケージマネージャは **uv**。`uv tool install .` でグローバルに `diet` コマンドを入れる。

### TypeScript / HPasaneel 側

- `recharts` — chart 描画（MVP 縮退時は外せる）

---

## 11. エラー処理・エッジケース

| 状況 | 動作 |
|---|---|
| Fitbit token 期限切れ | refresh token で自動更新、**新 token を DB に保存できてから API call**（single-use token rotation 対応）。401 の自動 retry は **1 回のみ** |
| token rotation 中のプロセス crash | DB 書き込みを SQLite transaction で atomic 化。crash 時は古い refresh token が残るので次回 refresh で再リトライ、それも失敗したら `diet auth` 再認証案内 |
| ネットワーク失敗 | Fitbit sync をスキップして警告、食事入力には進む（オフライン耐性）。publish もスキップ |
| Fitbit Rate Limit (150/h) | リクエスト数を自前カウント、`Fitbit-Rate-Limit-Reset` ヘッダを尊重。429 受領時は次回 reset まで sync 待機（食事入力は通常通り）|
| 当日体重が Renpho 未同期 | **対象日以前**の最新体重を使う（タイムマシン禁止）、「N 日前 (71.5kg) を使用」と警告 |
| 30 日以上前まで遡っても体重無し | `diet weight 71.2` での手動入力を促す |
| 食事 0 kcal（断食日） | 許可 |
| 食事入力スキップ（Enter） | 「未記録」扱い。収支表示はスキップ、publish は運動・体重のみ実行 |
| 過去日入力 | `diet --date 2026-05-23` で全フローが過去日で動く。年齢・体重も対象日基準。publish も該当日の entry を更新 |
| 同じ日に複数回 publish | log.json の該当 entry を上書き、commit メッセージは `diet: 2026-05-25 update (rev N)` |
| HPasaneel に未コミット変更あり | 「他に未コミット変更があります、続けますか? [y/N]」を確認。yes なら log.json のみ stage |
| `content/diet/log.json` に手動変更あり | 「log.json を上書きしますか? [y/N]」確認。no なら publish 中止 |
| `git pull --rebase` 失敗 | 手動解決を促して publish 中止（diet は exit code 非 0 で終了）|
| `git push` 失敗 | エラー出力をそのまま表示、手動解決を促す |
| Fitbit 未装着（steps=0） | そのまま記録。BMR だけの収支になる（24h 装着しない前提を尊重） |
| `diet init` 未実行で `diet` を実行 | 「先に `diet init` を実行してください」と案内 |
| `diet calibrate` 未実行で `diet` を実行 | `marginal` を暫定使用しつつ「`diet calibrate` を推奨」警告 |

---

## 12. テスト方針

- **`bmr.py`** — 純粋関数なので網羅的ユニットテスト
  - 過去日入力時の年齢計算（生年月日跨ぎを含む）
  - Asia/Tokyo と UTC の境界日テスト
- **`publish.py`** — 公開境界の二重担保:
  - **境界テスト**: `intake_events` に多様なデータを insert → publish 実行 → log.json に食事系フィールドが**絶対出ない**ことを diff で検証
  - **schema guard テスト**: 余計なフィールドを持つ DTO を渡したら例外で停止することを確認
  - 公開フィールドが `date / steps / distance_km / exercise_kcal / weight_kg` の 5 個のみであることを assert
- **`oauth.py`** — token rotation:
  - refresh 成功時の DB 保存が atomic（部分書き込みで壊れない）
  - rotation 中の crash 後の再起動で正しい復旧パス
- **`fitbit_client.py`** — httpx mock で OAuth・rate limit・API レスポンス処理
- **`db.py`** — テンポラリ SQLite でスキーマ migration テスト
- 全体結合テストは VCR.py のような HTTP リプレイで（実 API は叩かない）

---

## 13. スコープ外（将来検討）

- 心拍・睡眠データ取得
- 食事の食品 DB 検索（あすけん的）
- 写真からのカロリー AI 推定
- LINE/Slack bot 連携
- 自動スケジューラ（Windows タスクスケジューラから定時実行）
- ダッシュボードの認証（現状は public、それで困ったら追加検討）
- 体重以外の Renpho 計測値（体脂肪率・筋肉量）の取り込み

---

## 14. 未確定事項（実装中に決める or 後追い）

- OAuth callback port `8765` の競合可否確認
- log.json のレコード数上限（数年運用後の bundle サイズ対策。1 年 365 行で十分小さいので当面気にしない）
- ダッシュボード UI の具体デザイン（HPasaneel の既存トーンに合わせる）
- `exercise_calorie_source` の最終決定は MVP 出荷後 2 週間の calibrate 期間で確定

---

## 付録 A: codex review 反映ログ（rev 2, 2026-05-25）

| codex 指摘 | 反映場所 |
|---|---|
| HIGH: `activityCalories` は BMR 含む、二重計上の罠 | § 4 重要な仕様、§ 6 DB スキーマ（候補 2 列保存）、§ 8 calibrate コマンド新設 |
| Medium-2: 公開境界の allowlist 2 層化 | § 7 typed DTO + jsonschema guard、§ 12 二重テスト |
| Medium-3: 年齢を Asia/Tokyo の対象日基準で、体重は対象日以前限定 | § 2、§ 3、§ 11 体重 fallback の文言修正 |
| Medium-4: refresh token の atomic 保存 | § 6 fitbit_token テーブル、§ 11 token 行、§ 12 oauth テスト |
| Low-1: rate limit カウント・ヘッダ尊重 | § 9 fitbit_client.py 役割、§ 11 rate limit 行 |
| Low-2: git push の安全シーケンス | § 7 git 連携セクション全面書き直し |
| Scope: calibration コマンド追加、recharts/nav は MVP 縮退可 | § 8 diet calibrate 新設、§ 7 縮退オプション明記 |
