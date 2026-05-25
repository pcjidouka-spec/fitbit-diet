# Fitbit 連動ダイエット CLI — 設計書

- 作成日: 2026-05-25
- 最終更新: 2026-05-25（override authoritative / sample floor / bootstrap baseline, rev 7）
- ステータス: ユーザーレビュー待ち
- スコープ: 2 リポジトリ横断
  - `C:/code/fitbit連動ダイエット` — Python CLI（本リポジトリ）
  - `C:/code/HPasaneel` — Next.js ダッシュボードページ追加

---

## 1. 目的と方針

「食べた分だけ歩く・走る」をパーソナル運用するための CLI ツールを作る。

- **食事カロリー（kcal 数値）**: CLI で手入力（全食事を必ずしも記録しない前提）。記録されない時は **過去 14 日の記録あり日の平均**で補完。dashboard には出さないが、運動・体重から「逆算されてしまう」ことは許容する
- **食事メニュー（note 文字列）**: ★最重要秘匿対象★ 絶対に公開しない
- **運動データ・体重**: Fitbit Web API 経由で取得、HPasaneel に公開
- **基礎代謝（BMR）**: 生年月日・身長・性別と当日体重から自動算出
- **収支**: 摂取 vs (BMR + 運動消費) を毎回算出（CLI 内のみ表示）
- **公開**: 運動データと体重のみを HPasaneel に日次でダッシュボード公開

「見られている」プレッシャーをダイエットの動機付けに使う。

**プライバシー境界の本質（rev 5 で再定義）:** 公開しないものは 2 種類あり、保護レベルが違う:

| 項目 | 保護レベル | 理由 |
|---|---|---|
| `intake_events.note`（メニュー名等） | ★絶対秘匿。構造的に公開不能 | 「何を食べたか」は本人の食生活・嗜好情報、人格に紐づく |
| `intake_events.kcal`（摂取カロリー数値） | dashboard には出さない | 出さないが、運動 + 体重変動から推測される可能性は許容 |

`kcal` を保護せず `note` のみを絶対秘匿対象とするので、公開境界の allowlist 2 層防衛（§ 7）は **特に `note` の漏洩を防ぐ**ことが第一目的になる。

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
    = 10 × 体重 + 1056.25 − 5 × 年齢 + 5
    = 10 × 体重 − 5 × 年齢 + 1061.25
```
例: 体重 70kg, 年齢 46 歳 → 700 + 1056.25 − 230 + 5 = 1531 kcal/日

**実装時の定数（コピペ防止のため明示）:**
- `HEIGHT_TERM = 6.25 * 169 = 1056.25`
- 計算は `bmr = 10 * weight + 1056.25 - 5 * age + 5` を式そのまま書く（定数を畳まない）

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

1. **`summary.marginalCalories`（デフォルト）** — Fitbit の中で「基礎代謝を引いた、活動由来っぽい消費」に最も近い。装着していない時間が長いとノイズが乗るが、構造的に基礎代謝を含まないので二重計上リスクが最小。`exercise_calorie_source` が未確定のあいだは **デフォルトで marginal を使う**
2. **`activities[].calories`** — ユーザーが明示的に記録した運動エントリの合計。意味は明確だが、運動時間中の resting burn（基礎代謝分）を含む可能性があり、未補正だと部分的に二重計上になる。採用する場合は運動時間 × 時間当たり BMR を引いて補正するか、calibrate で実測比較した上で許容する
3. **`summary.steps × 体重 × 係数` で独自算出** — 装着精度に依存しすぎる場合の最終 fallback

**MVP は `marginalCalories` と `activities[].calories` の両方を取得して DB に保存**し、`diet calibrate` コマンド（§ 8）で数日分を並べて表示。ユーザーが calibrate で source を確定するまでは marginal を使う。確定後は config に `exercise_calorie_source` を保存して以降そちらを使う。

---

## 4.5 食事 kcal の解釈ロジック（rev 7 で大幅改訂）

ユーザーは毎食必ず記録するとは限らないので、`intake_events` から **対象日の摂取 kcal（intake_kcal）** をランタイム算出する（テーブルに保存しない）。

### 核となる区別: complete day vs partial day

| 種別 | 定義 | 性質 |
|---|---|---|
| **complete day** | その日に **`op='override'` の event が 1 件以上**含まれる日 | 「今日の合計は X」とユーザーが宣言した日。authoritative。past_avg のサンプルプールに入る |
| **partial day** | events はあるが `op='override'` が 0 件（`+` のみ）| 部分入力の可能性、authoritative ではない。サンプルプールには入らない |
| **empty day** | events が 0 件 | 何もない |

### 用語

- **today_events**: 対象日 (Asia/Tokyo) の `intake_events` を `ORDER BY timestamp ASC, id ASC` で取得
- **recorded_sum**: today_events から op セマンティクスで算出した合計（None なら events 0 件）
- **past_avg**: 過去 14 日のうち **complete day** の `recorded_sum` 平均
- **N_samples**: past_avg を構成した complete day の件数
- **SAMPLE_FLOOR**: 3（これ未満なら past_avg を信頼しない、設定値）
- **bootstrap_baseline**: `diet init` で任意で聞いた「普段 1 日 X kcal くらい」の値（未設定なら None）

### recorded_sum の算出（op セマンティクス）

events を時系列順に走査、最後の `op='override'` を境にロジック切替:

- events 空 → `recorded_sum = None`
- 最後の override 以降:
  - override.kcal が基底値、その後の append.kcal をすべて加算
- override が一度も無く append のみ → 全 append の合計
- 例（時系列順）:
  - `[+500, +300]` → 800（partial day）
  - `[+500, =2000, +200]` → 2200（complete day、override 後の +200 を加算）
  - `[=2000]` → 2000（complete day）
  - `[=0]` → 0（complete day、断食日）
  - `[=2000, =1500]` → 1500（complete day、後勝ち）

**deterministic order**: 同 timestamp の events が複数ある時は `id ASC` で安定化（コードレビューで衝突が起きないように明示）。

### past_avg の算出

```sql
WITH per_day AS (
  SELECT date,
         <recorded_sum 算出と同じロジック> AS sum,
         MAX(CASE WHEN op = 'override' THEN 1 ELSE 0 END) AS has_override
  FROM intake_events
  WHERE date >= target_date - 14 days  -- ★ JST 日付で半開区間 [target_date - 14, target_date)
    AND date <  target_date
  GROUP BY date
)
SELECT AVG(sum), COUNT(*)
FROM per_day
WHERE has_override = 1   -- ★ complete day のみ
```

- **日付窓は JST 日付で `[target_date - 14, target_date)` の半開区間**（target_date - 14 を含み、target_date を含まない）
- **complete day が 0 件 → past_avg = None, N_samples = 0**
- 確定した N_samples は 4 ケース分岐の判断と表示に使う

### 最終 intake_kcal の決定（rev 7 完全書き直し）

優先順位を上から評価:

| 条件 | intake_kcal | label | 表示例 |
|---|---|---|---|
| today に **override が 1 件以上** (complete day) | `recorded_sum` | `recorded_authoritative` | 「記録 1800 kcal」 |
| today は partial で `recorded_sum is not None` & `past_avg` あり (N_samples ≥ SAMPLE_FLOOR) | `max(recorded_sum, past_avg)` | recorded ≥ avg → `recorded_partial_high`、recorded < avg → `estimated_avg_supplement` | 前者「記録 2400 kcal (部分入力)」、後者「推定 2100 kcal (記録 500 + 平均補完 1600、N=11)」|
| today は partial で `recorded_sum is not None` & avg なし or N_samples < SAMPLE_FLOOR | `max(recorded_sum, bootstrap_baseline)` if baseline あり、else `recorded_sum` | `estimated_baseline_supplement` / `recorded_no_baseline` | 「推定 2000 kcal (記録 500 + baseline 補完 1500)」 |
| today empty & past_avg あり (N_samples ≥ SAMPLE_FLOOR) | `past_avg` | `estimated_avg` | 「推定 1980 kcal (過去 14 日 complete day 平均, N=8)」 |
| today empty & avg なし or N_samples < floor & baseline あり | `bootstrap_baseline` | `estimated_baseline` | 「推定 2000 kcal (init baseline)」 |
| today empty & avg なし & baseline なし | `None` | `unconfirmed` | 「摂取量未確定 (記録なし、complete day が N 件しかない、baseline 未設定)」 |

### 設計判断

- **override が authoritative** な理由: `=0` 断食日や `=1200` 制限日が past_avg で水増しされたら設計目的が壊れる。codex rev6 指摘 #1
- **complete day のみ past_avg のサンプルプール** な理由: partial 日を混ぜると平均が体系的に低くなる。codex rev6 指摘 #6
- **SAMPLE_FLOOR=3** な理由: 1〜2 日では平均値の意味が薄い、ノイズが大きい。3 件以上で「過去日の代表値」として使う。codex rev6 指摘 #3
- **bootstrap_baseline** な理由: 運用初期や complete day が 3 件未満の cold start 期に「未確定」連発を回避するための任意 fallback。silent invent は禁止、`diet init` で明示的に聞く。codex rev6 指摘 #4
- **半開区間 `[target_date - 14, target_date)`** な理由: 包含/排他の曖昧さを排除、過去 14 日 = 14 個の calendar day と一致。codex rev6 指摘 #5
- **`max(recorded, avg)` は partial day 限定** な理由: complete day は authoritative なので max を適用しない（適用するとユーザーの「これが今日の合計だ」宣言を無視することになる）
- **平均はランタイム計算** → 過去日修正・新規追加で過去平均値が遡って更新される。テーブルにキャッシュしない
- **`intake_kcal = None` の時** → § 5 [4] 収支表示は「摂取量未確定のため収支算出不可」と表示し、publish は通常通り（運動・体重のみ）実行する

---

## 5. アーキテクチャ（B 案: 単一コマンド対話型）

`diet` 1 コマンドで 1 日分が完結する対話フロー:

```
$ diet
[1/5 Fitbit同期] 運動データ取得中...
    歩数 8,234 / 距離 5.3km
    運動消費 280kcal (source: marginal)
    体重 71.2kg (Renpho→Fitbit経由、2026-05-25 計測)

[2/5 食事入力] 今日のカロリー (現在の累積: 1,800kcal)
    入力 (+追加 / =上書き / Enter=skip):
    > +500
    累積 2,300kcal (記録)

  ※ 表示パターンの例（§ 4.5 の決定表に対応）:
    [今日 override あり、`=2300` 入力]      → 「記録 2,300kcal」（authoritative）
    [今日 partial、入力 < 平均、N=11]       → 「推定 2,100kcal (記録 500 + 平均補完 1,600、過去 N=11)」
    [今日 partial、入力 ≥ 平均]             → 「記録 2,400kcal (部分入力、過去平均超え)」
    [今日 empty、N=8]                       → 「推定 1,980kcal (過去 14 日 complete day 平均、N=8)」
    [今日 empty、N<3、baseline=2000]        → 「推定 2,000kcal (init baseline、complete day N=2 のため平均未使用)」
    [今日 empty、N=0、baseline 未設定]      → 「摂取量未確定」（収支算出スキップ）

[3/5 基礎代謝] BMR (46歳/男性/169cm/71.2kg) = 1,543kcal

[4/5 収支] 摂取 2,300 vs 消費 (BMR 1,543 + 運動 280) = -477kcal (赤字)
    黒字化まで あと約 11,900歩 (または 走 3.4km)
    ※ 摂取が「推定」表示の時は収支も「推定」とラベル表示

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
  exercise_calorie_source TEXT,       -- 'logged_activities' | 'marginal' | 'steps_estimated'
                                      -- 初期は NULL、calibrate 後に確定
  bootstrap_daily_kcal   INTEGER      -- diet init で任意で入れる「普段 1 日 X kcal」
                                      -- cold start 期の fallback、未設定なら NULL
)

-- 食事イベント（1 回ごと append）
-- kcal: dashboard には出さないが逆算は許容
-- note: ★最重要秘匿、絶対に公開境界を越えない
intake_events (
  id            INTEGER PRIMARY KEY,
  date          DATE,        -- YYYY-MM-DD（Asia/Tokyo で正規化）
  timestamp     DATETIME,    -- 入力時刻
  kcal          INTEGER,
  op            TEXT,        -- 'append' or 'override'
  note          TEXT         -- ★メニュー名等。絶対秘匿、構造的に publish 不能にする
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
- **公開境界の物理分離** → § 7 で詳述。publish 関数は `daily_activity` と `daily_weight` のみ SELECT し、`intake_events` に触らないことをユニットテストで担保（特に `note` が漏れない保証が最重要）
- **time zone は Asia/Tokyo 固定** → 日付境界は JST の 0 時
- **Fitbit カロリー候補を 2 列で保存** → calibration 期間中も後追いでも比較可能

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

**公開フィールドの allowlist 2 層防衛（codex Medium-2 対応, rev3 で厳密化）:**

1. **typed DTO 層** — `publish.py` 内で `@dataclass class PublicDayRecord` を定義し、`date / steps / distance_km / exercise_kcal / weight_kg` のみフィールドに持たせる。DB から DTO への変換は明示的にこの 5 フィールドだけを SELECT して**手で詰める**
2. **JSON schema guard 層** — `log.json` 書き出し直前に `jsonschema` でバリデーション

**DTO → JSON 変換契約（実装時の禁則事項）:**
- `dataclasses.asdict()` / `__dict__` / `row._asdict()` 等の自動シリアライズを **使わない**。手書きの `to_public_dict()` メソッドで 5 フィールドだけを dict に詰める
- 既存 `log.json` の merge 手順は厳密に以下の順:
  1. 既存ファイルを raw dict として読み込み
  2. **読み込み直後に schema validate**（未知フィールドが混入してたらここで例外停止、silent drop させない）
  3. DTO に詰め直して正規化
  4. 対象日 entry を新データで差し替え or 追加して merge
  5. **書き出し直前にもう一度 schema validate**（final dict が schema に従ってることを確認）
  6. ファイル書き出し
- raw dict と DTO 化 dict の **両方** で schema validate する 2 段構え

**JSON schema 仕様:**
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "required": ["updated_at", "days"],
  "properties": {
    "updated_at": {"type": "string", "format": "date-time"},
    "days": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["date", "steps", "distance_km", "exercise_kcal", "weight_kg"],
        "properties": {
          "date":          {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
          "steps":         {"type": "integer", "minimum": 0},
          "distance_km":   {"type": "number", "minimum": 0},
          "exercise_kcal": {"type": "integer", "minimum": 0},
          "weight_kg":     {"type": "number", "minimum": 0}
        }
      }
    }
  }
}
```

`additionalProperties: false` を **top level と days.items の両方** に明記。`updated_at` はトップレベル 1 個のみ、JSON 全体が「最終生成時刻」を持つ。これは公開して問題ない情報と判断（ユーザー本人の公開意図）。

**git 履歴の不可逆性:** 一度 push した体重等は git history に永久に残る。ロールバックしたければ push 前の段階で訂正する。push 後の訂正は新 commit になり、過去 commit には残り続けることをユーザーは認識しておく。

### git 連携 — 安全な実行シーケンス（codex Low-2 対応）

```bash
cd <hpasaneel_path>
git status --porcelain content/diet/log.json    # log.json に手動変更が無いか確認
# 手動変更があれば対話で「上書きしますか? [y/N]」、no なら publish 中止
git pull --rebase                                # リモートとの差分取り込み

# ★重要: diet は pull 後の log.json をディスクから読み込み直し、
#       (1) raw 読み込み直後に schema validate(未知フィールドは silent drop されない)
#       (2) DTO 化、対象日 entry のみ差し替え、他日 entry は保持
#       (3) 書き出し直前にもう一度 schema validate
#       (4) ファイル書き出し
#       リモートで他端末/別プロセスが追加した「新しい日付の entry」を絶対消さない。

# stage は log.json のみ限定指定
git add content/diet/log.json
git commit -m "diet: 2026-05-25 update"
git push          # → Cloudflare Pages auto deploy
```

- **HPasaneel に他の未コミット変更がある場合** → log.json 以外には触らない（`git add .` は禁止）。確認プロンプトを出す
- **`pull --rebase` 失敗** → 手動解決を促して終了
- **同じ日の再 publish** → log.json の該当 entry を上書き、他日 entry は保持、commit メッセージは `diet: 2026-05-25 update (rev N)`
- **過去日 publish (`--date`)** → 該当日 entry のみ差し替え、他日に影響なし

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
普段 1 日に食べているカロリーの目安 (cold start fallback、不明なら Enter で skip):
  > 2000

→ data/diet.db 作成、config 保存 (bootstrap_daily_kcal=2000)
→ Fitbit OAuth フロー起動（ブラウザが開く）
→ http://localhost:8765/callback で token 受け取り → DB 保存
→ 初回 sync 実行（過去 30 日分を遡って取得、カロリー 2 候補を両方保存）
→ 「次に `diet calibrate` を実行して exercise_kcal の値を決めてください」と案内
```

bootstrap baseline は **complete day が 3 件未満（SAMPLE_FLOOR）の cold start 期** だけ使われる。complete day が貯まれば自動的に past_avg が優先される。後から `diet baseline 2200` で更新可能（rev 7 で CLI 追加、§ 9 参照）。

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
      cli.py             # click/typer 定義（下記コマンド一覧参照）
      fitbit_client.py   # Fitbit Web API ラッパー + rate limit tracking
      oauth.py           # OAuth フロー + localhost callback server + atomic token rotation
      bmr.py             # BMR 計算（純粋関数、target_date 引数で過去日対応）
      intake.py          # 食事 kcal 算出（recorded_sum / past_avg / final intake_kcal の純粋関数）
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

### CLI コマンド一覧（rev3 で `diet weight` 追加）

| コマンド | 役割 |
|---|---|
| `diet` | 1 日分の対話フロー（Fitbit sync → 食事入力 → 収支 → publish） |
| `diet --date 2026-05-23` | 過去日対象で対話フロー実行 |
| `diet init` | 初期セットアップ（profile + OAuth + 初回 sync） |
| `diet auth` | OAuth token を再取得（refresh 完全失敗時の復旧） |
| `diet calibrate` | Fitbit カロリー候補を並べて `exercise_calorie_source` を決定 |
| `diet weight 71.2` | 体重を手動入力（Renpho 同期不全時の fallback、当日 or `--date` 指定可） |
| `diet sync` | Fitbit sync のみ実行（対話なし、cron 用） |
| `diet show [--date YYYY-MM-DD]` | 指定日（デフォルト今日）の収支を表示のみ（食事入力・publish なし） |
| `diet baseline 2200` | bootstrap_daily_kcal の更新（cold start 期の見直し用） |

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
| Fitbit token 期限切れ | refresh token で自動更新、**新 token を DB に commit してから API call** に進む（single-use token rotation 対応）。401 の自動 retry は **1 回のみ** |
| token rotation 中のプロセス crash | 完全には防げないが緩和: (1) DB 書き込みを `BEGIN IMMEDIATE` transaction で atomic 化、(2) refresh 開始前に `flock` 相当のプロセスロック取得で並列 refresh 防止、(3) crash で新 refresh token を失った時は次回起動で `diet auth` 再認証を促す（古い single-use token は既に Fitbit 側で無効化されてる前提）|
| ネットワーク失敗 | Fitbit sync をスキップして警告、食事入力には進む（オフライン耐性）。publish もスキップ |
| Fitbit Rate Limit (150/h) | リクエスト数を自前カウント、`Fitbit-Rate-Limit-Reset` ヘッダを尊重。429 受領時は次回 reset まで sync 待機（食事入力は通常通り）|
| 当日体重が Renpho 未同期 | **対象日以前**の最新体重を使う（タイムマシン禁止）、「N 日前 (71.5kg) を使用」と警告 |
| 30 日以上前まで遡っても体重無し | `diet weight 71.2` での手動入力を促す |
| 食事 0 kcal（断食日） | 許可 |
| 食事入力スキップ（Enter）| § 4.5 の決定表に従う: complete day が N≥3 あれば past_avg、なければ bootstrap_baseline、それも無ければ「摂取量未確定」で収支算出スキップ。publish は運動・体重のみ実行 |
| 過去 14 日の complete day が 0 件かつ bootstrap_baseline 未設定（運用初期）| 「摂取量未確定」と表示、収支は出さない。`diet baseline X` で baseline 設定を促す |
| `=0` 入力（断食日）| complete day として 0 kcal で確定、past_avg や baseline で水増ししない |
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

- **`intake.py`** — 食事 kcal 算出（純粋関数、テスト容易）:
  - `recorded_sum` の op セマンティクス:
    - `[+500, +300]` → 800 (partial)
    - `[+500, =2000, +200]` → 2200 (complete, override 後の append 加算)
    - `[=2000]` → 2000 (complete)
    - `[=0]` → 0 (complete、断食日)
    - `[=2000, =1500]` → 1500 (complete、後勝ち)
    - 同 timestamp 複数 → `id ASC` で決定的
  - complete day 判定: events に `op='override'` が 1 件以上含まれるか
  - `past_avg` 算出:
    - complete day のみサンプル
    - **N_samples < SAMPLE_FLOOR (=3) なら past_avg を None 扱い**
    - 日付窓は JST `[target_date - 14, target_date)` の半開区間（境界日テスト必須）
    - 過去 14 日に complete day 0 件 → past_avg=None
    - 過去 14 日に complete day 2 件 → past_avg=None (floor 未達)
    - 過去 14 日に complete day 3 件 → past_avg=平均、N_samples=3
  - `intake_kcal` の 6 ケース分岐表すべてをテスト（§ 4.5 表のすべての行）
  - bootstrap_baseline 適用シナリオ（N<floor で baseline あり / なし）
  - `=0` 断食日が past_avg・baseline で水増しされないこと（最重要回帰防止テスト）
  - 過去日修正で N_samples と past_avg が再計算されること（キャッシュなし）
  - 表示文字列フォーマット: 各 label に対応するメッセージ生成
- **`bmr.py`** — 純粋関数なので網羅的ユニットテスト
  - 過去日入力時の年齢計算（生年月日跨ぎを含む）
  - Asia/Tokyo と UTC の境界日テスト
  - **必須テストケース** (birthday=1979-12-01):
    - `target_date=2026-11-30` → 年齢 46
    - `target_date=2026-12-01` → 年齢 47（誕生日当日で 1 歳加算）
    - `target_date=2026-12-02` → 年齢 47
    - `target_date=1979-12-01` → 年齢 0
    - UTC で日付跨ぎでも Asia/Tokyo で同じ日なら同じ年齢を返すこと
  - BMR 定数の検算: 体重 70.0 / 年齢 46 → `bmr == 1531.25`（小数 2 桁まで）
- **`publish.py`** — 公開境界の二重担保:
  - **境界テスト**: `intake_events` に多様なデータ（特に **note に "ラーメン特盛"**, "焼肉ホルモン" 等の生々しい文字列を含む）を insert → publish 実行 → log.json に **note 文字列が一切現れない**ことを diff で検証
  - kcal は方針上 dashboard 非公開なので、`intake_events.kcal` の値が log.json に出ないことも併せて assert
  - **schema guard テスト**: 余計なフィールドを持つ DTO を渡したら例外で停止することを確認
  - 公開フィールドが `date / steps / distance_km / exercise_kcal / weight_kg` の 5 個のみであることを assert
- **`publish.py`** — DTO 変換契約:
  - `to_public_dict()` が 5 フィールドだけ返すこと、余計なフィールドを混入させても DTO 経由で削られること
  - 既存 log.json を merge するとき、未知フィールドが含まれてたら **raw 段階の schema validate で**例外（DTO で silent drop されないこと）
  - 書き出し直前の final dict schema validate でも余計フィールドを reject すること
  - 2 段 validate が両方走ることをテストで確認（前段だけ走って後段がスキップされない）
- **`oauth.py`** — token rotation:
  - refresh 成功時の DB 保存が atomic（部分書き込みで壊れない、`BEGIN IMMEDIATE`）
  - rotation 中の crash 後の再起動で正しい復旧パス（`diet auth` 案内）
  - 並列 `diet` 実行でも同時 refresh が起きないこと（プロセスロック動作）
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

## 付録 A: codex review 反映ログ

### rev 2 (2026-05-25)
| codex 指摘 | 反映場所 |
|---|---|
| HIGH: `activityCalories` は BMR 含む、二重計上の罠 | § 4 重要な仕様、§ 6 DB スキーマ（候補 2 列保存）、§ 8 calibrate コマンド新設 |
| Medium-2: 公開境界の allowlist 2 層化 | § 7 typed DTO + jsonschema guard、§ 12 二重テスト |
| Medium-3: 年齢を Asia/Tokyo の対象日基準で、体重は対象日以前限定 | § 2、§ 3、§ 11 体重 fallback の文言修正 |
| Medium-4: refresh token の atomic 保存 | § 6 fitbit_token テーブル、§ 11 token 行、§ 12 oauth テスト |
| Low-1: rate limit カウント・ヘッダ尊重 | § 9 fitbit_client.py 役割、§ 11 rate limit 行 |
| Low-2: git push の安全シーケンス | § 7 git 連携セクション全面書き直し |
| Scope: calibration コマンド追加、recharts/nav は MVP 縮退可 | § 8 diet calibrate 新設、§ 7 縮退オプション明記 |

### rev 7 (2026-05-25) — intake fallback 厳密化
| codex 指摘 | 反映場所 |
|---|---|
| #1 HIGH: `=0` 断食日が max(recorded,avg) で水増しされる | § 4.5 complete day = authoritative とし、override 日は max を適用しない。決定表を 6 ケースに拡張 |
| #6 HIGH: past_avg のサンプルに partial 日が混ざると体系的に低下 | § 4.5 past_avg のサンプルプールを **complete day のみ** に限定 |
| #2 MEDIUM: events の deterministic order | § 4.5 `ORDER BY timestamp ASC, id ASC` 明記、§ 12 テスト |
| #3 MEDIUM: sample size floor | § 4.5 SAMPLE_FLOOR=3 導入、未達なら past_avg を信頼しない |
| #4 MEDIUM: cold-start bootstrap baseline | § 6 config に `bootstrap_daily_kcal`、§ 8 init 対話に追加、§ 9 CLI に `diet baseline` 追加、§ 4.5 fallback 順 (past_avg → baseline → 未確定) |
| #5 LOW: 14 日窓の半開区間明示 | § 4.5 `[target_date - 14, target_date)` JST、§ 12 境界テスト追加 |

### rev 6 (2026-05-25) — intake kcal 平均補完
| 変更内容 | 反映場所 |
|---|---|
| 「全食事は記録しない」前提を § 1 に明記 | § 1 食事カロリー行 |
| `intake_kcal` の算出ロジックを新セクションで詳述（recorded_sum + past_avg + max 採用）| § 4.5 新設、op セマンティクス・4 ケース分岐表 |
| 対話フロー [2] の表示パターンを 3 種類（記録 / 推定 / 部分入力）に拡張 | § 5 対話フロー |
| エッジケース行 2 件追加（スキップ時推定、運用初期データ不足）| § 11 |
| `intake.py` モジュールを新規追加（純粋関数）| § 9 構成、§ 12 テスト |

### rev 5 (2026-05-25) — privacy policy clarification
| 変更内容 | 反映場所 |
|---|---|
| プライバシー保護対象を「食事系全体」から「食事メニュー (note) のみ★絶対秘匿」に再定義 | § 1 目的と方針 全面書き直し、保護レベル 2 段階表を追加 |
| `intake_events.note` が境界保証の最重要対象であることを明示 | § 6 スキーマコメント、§ 12 境界テスト |
| 境界テストで note に生々しい文字列 ("ラーメン特盛" 等) を含めて漏洩検査を強化 | § 12 publish.py 境界テスト |

### rev 4 (2026-05-25) — codex loop closed
| codex 指摘 | 反映場所 |
|---|---|
| Medium: load 後の DTO 正規化で unknown field が silent drop され schema が catch しない | § 7 merge 手順を「raw load → schema validate → DTO → merge → schema validate → write」の 6 ステップに明文化、§ 12 で 2 段 validate のテストを明記 |
| Minor: § 5 サンプルの `source: activities[].calories` が default の marginal と不整合 | § 5 サンプル表示を `source: marginal` に修正 |

### rev 3 (2026-05-25)
| codex 指摘 | 反映場所 |
|---|---|
| HIGH: §3 BMR の `6.25 × 169 = 836.25` typo（正: `1056.25`）| § 3 数式を修正、定数明示で再発防止 |
| `marginalCalories` を safer default に | § 4 採用候補の優先順を marginal トップに変更・「未確定時 marginal を使う」明記 |
| `activities[].calories` は運動中 resting burn 二重計上の可能性 | § 4 候補 2 の説明に補正方針追記 |
| Publish 変換契約の厳密化（`__dict__` 等禁止、両層 `additionalProperties: false`）| § 7 「DTO → JSON 変換契約」追加、JSON schema 全文掲載 |
| Age 境界の test case 不足 | § 12 BMR テストに 4 cases 明記 |
| Token rotation の HTTP→DB 間 crash | § 11 token 行: `BEGIN IMMEDIATE` + プロセスロック明記 |
| Git: 再生成は post-pull の log.json を読み直して対象日のみ差し替え | § 7 git シーケンスにコメント追加 |
| MVP gap: `diet weight` が CLI 一覧にない | § 9 CLI コマンド一覧表を新設し `diet weight` 含む 8 コマンドを明記 |
