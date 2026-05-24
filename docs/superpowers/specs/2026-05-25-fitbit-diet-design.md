# Fitbit 連動ダイエット CLI — 設計書

- 作成日: 2026-05-25
- ステータス: 提案中（codex review 待ち）
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

年齢は実行時に生年月日から算出（毎年自動更新）。

---

## 3. BMR 計算式

ミフリン-セントジョー式（医療現場の標準、現代人での精度がハリス・ベネディクト式より高い）。

```
男性 BMR = 10 × 体重(kg) + 6.25 × 身長(cm) − 5 × 年齢 + 5
```

このプロファイルでは:
```
BMR = 10 × 体重 + 6.25 × 169 − 5 × 年齢(46〜) + 5
    = 10 × 体重 + 831.25 − 5 × (年齢 − 46)
```
例: 体重 70kg, 年齢 46 歳 → 1531 kcal/日

体重と年齢が毎日変動し得るため、テーブルに保存せず実行時に毎回再計算する。

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

**重要な仕様:** Fitbit デバイスは 24 時間装着しない前提のため、Fitbit が出す TDEE（基礎代謝込み消費）は使わず、**運動由来の消費のみ**を Fitbit から取得し、基礎代謝はこちらで算出して足し合わせる。

---

## 5. アーキテクチャ（B 案: 単一コマンド対話型）

`diet` 1 コマンドで 1 日分が完結する対話フロー:

```
$ diet
[1/5 Fitbit同期] 運動データ取得中...
    歩数 8,234 / 距離 5.3km / 運動消費 280kcal
    体重 71.2kg (Renpho→Fitbit経由)

[2/5 食事入力] 今日のカロリー (現在の累積: 1,800kcal)
    入力 (+追加 / =上書き / Enter=skip):
    > +500
    累積 2,300kcal

[3/5 基礎代謝] BMR (46歳/男性/169cm/71.2kg) = 1,543kcal

[4/5 収支] 摂取 2,300 vs 消費 (BMR 1,543 + 運動 280) = -477kcal (赤字)
    黒字化まで あと約 11,900歩 (または 走 3.4km)

[5/5 公開] HPasaneel に運動・体重のみ公開しますか? [y/N]: y
    → content/diet/2026-05-25.json 更新
    → git commit + push 完了
```

**ポイント:**
- 食事入力は **append（累積）** がデフォルト。`+500` で追加、`=2300` で上書き、Enter でスキップ
- 過去日修正は `diet --date 2026-05-23` で起動、全フローが過去日で動く
- Fitbit sync 失敗時は警告のみ出して食事入力に進む（オフライン耐性）
- 5 ステップは順に走り、ユーザー操作が必要なのは [2] 食事入力と [5] 公開可否のみ

---

## 6. データスキーマ（SQLite）

`data/diet.db` 1 ファイルで完結。`data/` ディレクトリは `.gitignore` 済み。

```sql
-- 設定（1 行のみ）
config (
  birthday      DATE,        -- '1979-12-01'
  height_cm     INTEGER,     -- 169
  sex           TEXT,        -- 'male'
  timezone      TEXT,        -- 'Asia/Tokyo'
  hpasaneel_path TEXT,       -- 'C:/code/HPasaneel'
  hpasaneel_diet_root TEXT   -- 'content/diet'
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
  date          DATE PRIMARY KEY,
  steps         INTEGER,
  distance_km   REAL,
  exercise_kcal INTEGER,
  last_synced   DATETIME
)

-- 体重（Renpho→Fitbit 経由・日次）  ← 公開対象
daily_weight (
  date          DATE PRIMARY KEY,
  weight_kg     REAL,
  last_synced   DATETIME
)

-- Fitbit OAuth token
fitbit_token (
  access_token   TEXT,
  refresh_token  TEXT,
  expires_at     DATETIME,
  user_id        TEXT
)
```

**設計判断:**
- **収支・BMR は保存しない** → 毎回算出（体重訂正で過去日が自動的に正しい値になる）
- **食事は append 履歴** → 全イベントを残し、`op='override'` も含めて履歴追跡可能
- **公開境界の物理分離** → publish 関数は `daily_activity` と `daily_weight` のみ SELECT する。`intake_events` に触らないことをユニットテストで担保
- **time zone は Asia/Tokyo 固定** → 日付境界は JST の 0 時

---

## 7. 公開仕様（HPasaneel 連動）

### 書き出しファイル

`C:/code/HPasaneel/content/diet/log.json` 1 ファイルに累積。

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

**公開フィールド（固定・絶対変更不可）:**
- `date`
- `steps`
- `distance_km`
- `exercise_kcal`
- `weight_kg`

食事 kcal、摂取、収支、BMR、身長、年齢、生年月日は構造的に絶対書き出されない。

### git 連携

```bash
cd <hpasaneel_path>
git add content/diet/log.json
git commit -m "diet: 2026-05-25 update"
git push          # → Cloudflare Pages auto deploy
```

publish 前に HPasaneel 側に他の未コミット変更がある場合は確認プロンプトを出す。`git add` は `content/diet/log.json` のみ限定指定し、他のファイルは巻き込まない。

### HPasaneel 側ダッシュボードページ（本プロジェクトで一緒に実装）

- `app/diet/page.tsx` を新規追加
- `content/diet/log.json` を import（Next.js の静的ビルドで bundle に同梱）
- 体重推移グラフ・歩数バー・距離・運動消費の表示
- chart ライブラリ: `recharts`（軽量、SSR 互換）を新規依存に追加
- メインナビゲーション（Company / Research / ... と並列）に "Diet" 項目を追加

---

## 8. 初回セットアップ

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
→ 初回 sync 実行（過去 30 日分を遡って取得）
→ 完了
```

---

## 9. プロジェクト構成

```
C:/code/fitbit連動ダイエット/
  src/
    diet/
      __init__.py
      __main__.py        # diet コマンド本体（対話フロー orchestrator）
      cli.py             # click/typer 定義
      fitbit_client.py   # Fitbit Web API ラッパー
      oauth.py           # OAuth フロー + localhost callback server
      bmr.py             # BMR 計算（純粋関数、テストしやすく）
      db.py              # SQLite 接続・スキーマ管理
      publish.py         # log.json 生成 + git 操作（公開境界）
      formatters.py      # CLI 表示整形
  tests/
    test_bmr.py
    test_publish_boundary.py  # publish が intake_events に触らないことを担保
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
- 標準ライブラリ: `sqlite3`, `datetime`, `zoneinfo`, `http.server`, `subprocess`

パッケージマネージャは **uv**。`uv tool install .` でグローバルに `diet` コマンドを入れる。

### TypeScript / HPasaneel 側

- `recharts` — chart 描画

---

## 11. エラー処理・エッジケース

| 状況 | 動作 |
|---|---|
| Fitbit token 期限切れ | refresh token で自動更新。refresh も失敗したら `diet auth` で再認証を促し終了 |
| ネットワーク失敗 | Fitbit sync をスキップして警告、食事入力には進む（オフライン耐性）。publish もスキップ |
| 当日体重が Renpho 未同期 | 直近 7 日以内の体重を使い、「N 日前 (71.5kg) を使用」と警告 |
| 7 日以上前まで遡っても体重無し | `diet weight 71.2` での手動入力を促す |
| 食事 0 kcal（断食日） | 許可 |
| 食事入力スキップ（Enter） | 「未記録」扱い。収支表示はスキップ、publish は運動・体重のみ実行 |
| 過去日入力 | `diet --date 2026-05-23` で全フローが過去日で動く。publish も該当日の entry を更新 |
| 同じ日に複数回 publish | log.json の該当 entry を上書き、commit メッセージは `diet: 2026-05-25 update (rev N)` |
| HPasaneel に未コミット変更あり | 「他に未コミット変更があります、続けますか? [y/N]」を確認。yes なら log.json のみ stage |
| git push 失敗（fast-forward 不可） | `git pull --rebase` を試行、それでも失敗したら手動解決を促す |
| Fitbit 未装着（steps=0） | そのまま記録。BMR だけの収支になる（24h 装着しない前提を尊重） |
| `diet init` 未実行で `diet` を実行 | 「先に `diet init` を実行してください」と案内 |

---

## 12. テスト方針

- **`bmr.py`** — 純粋関数なので網羅的ユニットテスト
- **`publish.py`** — 公開境界の担保:
  - `intake_events` テーブルに insert したデータが log.json に **絶対出ない**ことを検証
  - 公開フィールドが `date / steps / distance_km / exercise_kcal / weight_kg` のみであることを検証
- **`fitbit_client.py`** — httpx mock で OAuth・token refresh・API レスポンス処理
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

---

## 14. 未確定事項（実装中に決める or 後追い）

- OAuth callback port `8765` の競合可否確認
- Fitbit API レート制限への対応戦略（150 req/h/user）
- log.json のレコード数上限（数年運用後の bundle サイズ対策）
- ダッシュボード UI の具体デザイン（HPasaneel の既存トーンに合わせる必要あり）
