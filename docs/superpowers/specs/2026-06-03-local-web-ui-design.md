# ローカル Web UI（毎日フローのブラウザ化）— 設計書

- 作成日: 2026-06-03
- ステータス: 設計承認済み（brainstorm Section 1+2+3 完了）。実装 plan 未作成。
- スコープ: 本リポジトリ `C:/code/fitbit連動ダイエット` のみ（HPasaneel 側は変更なし）
- 関連: 既存 CLI 設計書 `2026-05-25-fitbit-diet-design.md`（rev 10 Google Health 移行込み）

> **目的:** 既存の対話型 CLI `diet` の毎日フロー（sync → 運動/体重表示 → 食事入力 → 収支 → publish）を、自宅 PC のブラウザで完結できるようにする。CLI は併存し続ける。

---

## 1. 背景と前提

- 利用場所は **自宅 PC のみ**に確定（スマホ案は秘匿境界の都合で却下）。
- 既存 Python モジュール（`db` / `google_health_client` / `publish` / `bmr` / `intake` / `orchestrator`）を**薄くラップ**する。ビジネスロジックの再実装はしない。
- OAuth（`diet auth`）は **v1 では CLI 据え置き**（別ポート callback の複雑化を避ける）。Web は auth 切れを検出してユーザーに CLI 再認証を促すだけ。
- 食事 `note` / `kcal` は **★絶対秘匿**（HPasaneel publish には絶対出さない）。この境界は CLI と同一コード（`publish.build_records_from_db`）で守る。

---

## 2. アーキテクチャ（Section 1+2）

### 構成

- **PC ローカル FastAPI サーバ**（`127.0.0.1` のみ bind）+ **素の HTML/JS** + **Chart.js をローカル同梱**（CDN 非依存）。
- 新コマンド `diet serve` を追加（CLI は併存）。
- 既存 `orchestrator.py` の**計算ロジックと click 対話 I/O を分離**し、Web/CLI 共用の純関数へ。

### モジュール構成（新規）

```
src/diet/web/
  app.py        # FastAPI アプリ定義・ルーティング・セキュリティミドルウェア
  service.py    # FastAPI 非依存の純 Python。DTO 組み立て・既存モジュール呼び出し
  static/       # index.html / app.js / chart.umd.min.js（ローカル同梱）
```

`orchestrator.py` からの抽出方針:
- 計算系（BMR・収支・intake 判定・past_avg）は既に `bmr` / `intake` / `formatters` / `helpers` に純関数として存在 → `service.py` はそれらを組み合わせるだけ。
- `_parse_kcal`（intake 入力パース）を **click 非依存の純関数へ切り出し**、CLI と Web で共用（二重実装しない）。例外は `ValueError` 等の汎用例外にし、click 層 / FastAPI 層がそれぞれ翻訳する。

### API エンドポイント

当日状態 DTO を中心に据える。

| メソッド | パス | 役割 |
|---------|------|------|
| `GET`  | `/api/day`            | 当日（または指定日）の状態 DTO（運動・体重・BMR・食事累積・収支） |
| `GET`  | `/api/history`        | 過去 N 日の履歴（グラフ用） |
| `POST` | `/api/sync`           | Google Health 同期（既存 `run_sync_async` の pass-through） |
| `POST` | `/api/intake`         | 食事入力（`+N` 追加 / `=N` 上書き） |
| `POST` | `/api/weight`         | 体重手動入力（任意） |
| `POST` | `/api/publish`        | HPasaneel publish（既存 `build_records_from_db` 不変） |
| `GET`  | `/api/auth/status`    | OAuth token の有効性確認 |

### データフロー

ブラウザ ⇄ `app.py`（セキュリティ検証 + HTTP 翻訳）⇄ `service.py`（純 Python）⇄ 既存モジュール ⇄ `data/diet.db` / Google Health API / HPasaneel git。

---

## 3. 秘匿・エラー・テスト（Section 3 / Codex consult 反映）

### 3.1 秘匿境界

CLI と Web で物理境界が変わる点を明確化する。

| データ | localhost ブラウザへ返す | HPasaneel publish へ出す |
|--------|:---:|:---:|
| 食事 kcal（累積・収支） | ✅ | ❌ 絶対 |
| 食事 note | ✅（編集 UI で必要時） | ❌ 絶対 |
| 歩数・距離・運動 kcal・体重 | ✅ | ✅（5 フィールド allowlist） |

**設計判断**:
1. **publish 経路は `build_records_from_db` 不変** — `daily_activity` + `daily_weight` のみ SELECT、2 段 allowlist（DTO `to_public_dict` + JSON schema `additionalProperties:false`）がそのまま効く。Web から publish しても境界コードは CLI と同一。
2. `/api/day`・`/api/intake` レスポンスに食事 kcal/note を載せるのは可。物理境界は **`127.0.0.1` バインド**。ただし下記 3.2 のとおり「バインドだけでは不十分」。
3. **境界テストを Web 層にも 1 本追加**: `/api/publish` 実行時に発行される SQL に `intake_events` が現れないことを既存 `set_trace_callback` 方式で assert。

### 3.2 localhost ブラウザセキュリティ（フルセット採用）

> Codex 指摘: `127.0.0.1` バインドは必要だが完全なブラウザセキュリティ境界ではない。ユーザーが踏んだ悪意あるサイトが DNS rebinding 等で `127.0.0.1:<port>` に fetch し、食事 note/kcal を窃取し得る。note が★絶対秘匿の本プロジェクトでは防御必須。

v1 で実装する防御（**フルセット**）:

1. **非ループバッククライアント拒否** — `app.py` ミドルウェアで peer IP がループバックでなければ拒否。
2. **Host ヘッダ検証** — `127.0.0.1:<port>` / `localhost:<port>` 以外を拒否（DNS rebinding 対策の要）。
3. **mutation 時 Origin チェック** — `POST` 系は `Origin` が自オリジンと一致しなければ拒否。
4. **permissive CORS 禁止** — CORS を一切緩めない（デフォルト same-origin のまま）。
5. **起動毎ランダム CSRF トークン** — サーバ起動時に生成し index.html に埋め込み、mutation で検証。
6. **`0.0.0.0` / `::` / 非ループバックホストでの起動を拒否** — `diet serve --host` 等で誤って外部公開しないよう起動時バリデーション。
7. **note は `textContent` で描画**（`innerHTML` 禁止）— stored XSS 対策。

### 3.3 エラーハンドリング（Codex 反映の HTTP semantics）

CLI の `try/except + echo警告` を HTTP に翻訳。**メッセージ文字列に依存しない安定エラーコードを JSON に併記**し、UI 挙動が文言に依存しないようにする。

| 事象 | HTTP | レスポンス方針 |
|------|:----:|----------------|
| sync 失敗（non-fatal） | **502 / 503** | 構造化 warning。UI はトースト表示し当日表示は続行（オフライン入力可）。`200` は「成功+非致命的警告」に予約 |
| config 未初期化 | **409** | 「`diet init` を実行」+ 安定コード |
| publish git 衝突（回復可能） | **409** | 手動解決 hint（`cd ... && git pull --rebase && git push`、CLI と同一文言）+ 安定コード |
| publish その他失敗 | **500** | hint + 安定コード |
| 入力バリデーション（`+N`/`=N`・非負整数） | **400** | 共用純関数パーサのメッセージ流用 + 安定コード |
| auth 切れ | （`/api/auth/status` で検出） | UI に「CLI で `diet auth` 再認証」を促す |

### 3.4 テスト戦略

1. **純関数抽出を先に** — `_parse_kcal` を click から切り出し。既存 159 tests が回帰防御として残る。
2. **`service.py` は FastAPI 非依存の純 Python** → DB fixture で単体テスト（`get_day_dto` 等）。
3. **API 層は FastAPI `TestClient`** → 各エンドポイントの 200/400/409/500/502 と sync non-fatal を検証。
4. **秘匿境界テスト必須**（3.1-3）。
5. **セキュリティテスト追加**（Codex）: loopback 強制 / Host・Origin 拒否 / CSRF / note エスケープ / リクエスト検証（JSON 必須）/ 重複 intake 送信挙動 / sync・publish 中の同時 SQLite アクセス。
6. **静的アセット**（HTML/JS/Chart.js）は自宅 PC で手動ブラウザ確認。E2E 自動化は v1 スコープ外。

---

## 4. 移行ライブ E2E との順序

**決定: 独立・Web UI 先行。** 2 トラックは実質独立で `google_health_client` を共有するだけ。

- Web `/api/sync` は既存 `run_sync_async`（= `google_health_client.py`）を**そのまま薄くラップ**。CLI sync と Web sync は同一コードパスを通る。
- ASSUMED フィールド問題は client 層にあり、**E2E で一度直せば CLI/Web 両方に効く**。Web UI を作っても sync の正しさに新たなリスクを足さない。
- Web UI の sync 以外（食事入力・体重/収支表示・publish）は**既存 DB データで E2E なしに完全にテスト可能**。
- ASSUMED フィールドは引き続き adapter に隔離し、fixture ベースの adapter テストを追加。sync は UI 上で「ライブ未検証」と明示。

---

## 5. v1 スコープ外（YAGNI）

- OAuth（`diet auth`）の Web 化 — v1 は CLI 据え置き。
- 食事の誤入力削除 `DELETE /api/intake/{id}` — MVP 外。
- マルチユーザー / リモートアクセス / 認証付き公開。
- E2E ブラウザ自動テスト。

---

## 6. 次ステップ

spec review → ユーザーレビュー → `writing-plans` で実装 plan 作成 → subagent-driven 実装。
