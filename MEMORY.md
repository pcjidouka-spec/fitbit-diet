# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `b72193b`（ローカル Web UI 実装完了 / PR #2）
最終更新日: 2026-06-03
GitHub: https://github.com/pcjidouka-spec/fitbit-diet / PR #1 (Google Health 移行, base main) / PR #2 (Web UI, base feat/fitbit-diet-cli)

★ **2026-06-03 完了: ローカル Web UI（`diet serve`）を実装完了**（feat/local-web-ui, 13 commit, 211 tests green, PR #2）。毎日フローをブラウザ(`127.0.0.1`)で完結。秘匿境界・localhost セキュリティはレビュー済み。**残: 自宅 PC での実ブラウザ手動確認 + sync のライブ Google Health 連携（トラック B 依存）**。詳細は § 4 (2026-06-03)。

★ **2026-06-01 完了: Fitbit Web API → Google Health API v4 移行を実装完了**（9 commit, PR #1）。コードは **code-complete・ライブ E2E pending**。**main へのマージは GCP セットアップ後のライブ E2E 検証が通るまで保留**（ASSUMED フィールドは adapter に隔離、実 API で要確認）。ASSUMED 項目は § 3、E2E 手順は § 5 トラック B。

---

## 1. 確定済み意思決定

| 決定事項 | 内容 | 決定日 |
|---------|------|--------|
| メモリー運用方式 | `MEMORY.md` を正本、`MEMORY_PENDING.md` を一時差分ログとして運用 | 2026-05-07 |
| AIツール | Claude Code のみ | 2026-05-07 |
| アーキテクチャ | B 案 = 単一対話型 CLI `diet` の 5 ステップ完結 | 2026-05-25 |
| 言語/環境 | Python 3.11+ / uv 管理 / `py -m uv run ...`（Windows） | 2026-05-25 |
| ユーザープロファイル | 生年月日 1979-12-01、身長 169cm、男性、Asia/Tokyo | 2026-05-25 |
| BMR 式 | Mifflin-St Jeor: `10*weight + 6.25*169 - 5*age + 5` | 2026-05-25 |
| 食事 fallback | 過去 14 日 complete day 平均 + bootstrap baseline、SAMPLE_FLOOR=3 | 2026-05-25 |
| 運動カロリー | `summary.marginalCalories` を default、`activities[].calories` も保持して calibrate で選択 | 2026-05-25 |
| 体重取得 | Renpho → Fitbit 同期 → Fitbit API | 2026-05-25 |
| プライバシー境界 | `intake_events.note` ★絶対秘匿。kcal は dashboard 非公開だが逆算許容 | 2026-05-25 |
| 公開先 | HPasaneel `content/diet/log.json` → `app/diet/page.tsx` (server) + `DietCharts.tsx` (client + recharts) | 2026-05-25 |
| OAuth callback | HTTPS 必須 → 自己署名証明書 + `https://localhost:8765/callback` | 2026-05-25 |
| codex review | 各 commit 直後に `codex review --commit <SHA>` 自動実行 | 2026-05-25 |
| 実装方式 | superpowers:subagent-driven-development（implementer + 必要に応じて review） | 2026-05-25 |
| **API 移行 (spec rev 10)** | Fitbit Web API → **Google Health API v4**（base `health.googleapis.com/v4`） | 2026-06-01 |
| 運動カロリー source | **active-energy-burned 固定**（BMR-free、`marginalCalories` 後継）。total-calories は診断保存のみ＝収支に不使用（BMR 二重計上回避）。calibrate は参照表示のみ | 2026-06-01 |
| OAuth | Google OAuth 2.0、**HTTP loopback callback**（自己署名証明書削除、`cryptography` 依存除去）、creds in body、refresh carry-forward、user_id は `/users/me/identity` から | 2026-06-01 |
| 同意画面 | **Production に publish 必須**（Testing だと refresh token 7 日失効）。単一ユーザー <100 でセキュリティレビュー不要 | 2026-06-01 |
| 旧 token 移行 | Fitbit token は転送不可 → v1→v2 migration で破棄し `diet auth` 再認証（体重/BMR 履歴は保全） | 2026-06-01 |
| DB 列改名 | `daily_activity`: `marginal_kcal→active_energy_kcal`, `logged_activities_kcal→total_calories_kcal`。token テーブル名は `fitbit_token` のまま保持 | 2026-06-01 |

---

## 2. 現在進行中のタスク

| タスク | ステータス | 次のアクション |
|-------|-----------|----------------|
| Phase 0-9 + 10.1 | ✅ 完了 (全 159 tests pass、HPasaneel dashboard 公開済み) | — |
| Google Health API 移行 (コード) | ✅ **実装完了** (9 commit, 159 tests, spec rev 10) | — |
| Phase 10.2 ライブ E2E | ⏸ **pending** (GCP 認証情報が必要) | § 5 トラック B の E2E チェックリスト実行 |
| PR #1 (Google Health 移行) | 作成済み・**マージ保留** | ライブ E2E 通過後に main へ merge |
| ローカル Web UI (毎日フロー) | ✅ **実装完了** (13 commit, 211 tests, PR #2) | 自宅 PC で実ブラウザ手動確認 → PR #2 を feat/fitbit-diet-cli へ merge |
| PR #2 (Web UI) | 作成済み (base=feat/fitbit-diet-cli) | 手動ブラウザ確認後に merge |

---

## 3. 未解決の課題・保留事項

| 課題 | 優先度 | 備考 |
|------|--------|------|
| **ライブ E2E 未実施** | **★ 高** | GCP 認証情報が必要。`docs/superpowers/plans/2026-06-01-google-health-api-e2e-checklist.md` 参照。完了まで PR #1 はマージ不可 |
| **ASSUMED フィールド要検証** | **★ 高** | `google_health_client.py` に隔離・コメント付き。実 API で要確認: distance rollup `meterSum`(meters)、total-calories `kcalSum`、identity `healthUserId`/`legacyUserId`、weight filter `weight.sample_time.civil_time`、rollup `value` 直キー。違えば adapter 1 行 + テスト 1 つの修正 |
| Renpho → Google Health 体重経路 | 中 | Renpho が Google Health に体重を流すか実アカウントで要確認 |
| recharts 依存に vulnerability 3 件 | 低 | d3 系の既知問題。pre-existing |
| `config.exercise_calorie_source` 列 | 低 | DEPRECATED・unused（active-energy 固定化後）。schema migration 回避のため列は保持、コメント明記済み |

---

## 4. セッションサマリー

### 2026-06-03 — ローカル Web UI 実装完了（PR #2）

brainstorm 再開（Section 3 を codex consult 反映で承認: 独立・Web UI 先行 / 秘匿 / localhost 防御フルセット / エラー semantics）→ spec 作成（reviewer 初回 Approved）→ writing-plans（reviewer 指摘 1 ブロッカー修正後 Approved）→ subagent-driven で 12 タスク実装。

**成果**: `feat/local-web-ui` 13 commit (`a1f3deb..b72193b`)、**211 tests green**、PR #2 作成（base=feat/fitbit-diet-cli）。`diet serve` で FastAPI(`127.0.0.1`)+素HTML/JS+同梱Chart.js。新 `src/diet/web/{service,security,app}.py` + static/templates。`parse_kcal` を intake.py に切り出し CLI/Web 共用、`run_sync_async`→`SyncOutcome` 返却。

**秘匿/セキュリティ**: publish は `build_records_from_db` 不変（食事 kcal/note は localhost のみ・publish 非漏洩、SQL トレーステストで実証）。Host/Origin/CSRF/loopback 防御 + 特権ポート拒否 + textContent 描画(XSS 防止)。

**codex 主導で修正した堅牢化**: 部分 sync 失敗の可視化(SyncOutcome)、token 失効/不在の reauth 信号、publish 失敗の細分コード(publish_no_data/blocked/git_failed/schema_invalid)、ポート解析の例外封じ込め、date クエリの 422 検証。最終統合レビュー **Ship**。

**codex**: PR #2 の全 code コミットを review 済み＝**clean**（c69017a の P2×3+P3×1 は次コミット d6b68af で自己修正済みと確認）。再レビュー不要。

**残**: ① 自宅 PC で実ブラウザ手動確認 ② sync の実 Google Health はトラック B（移行 E2E）依存。

### 2026-06-02 — ローカル Web UI brainstorm（毎日フローのブラウザ化、中断中）

**経緯**: 「CLI 対話フローをダッシュボードに組み込めないか」から brainstorm 開始。利用場所を確認 → **自宅 PC のみ**に確定（スマホ案は秘匿境界の都合で却下）。スコープ = **毎日の全フロー**（sync→運動/体重表示→食事入力→収支→publish）をブラウザで完結。

**承認済み設計（Section 1+2）**:
- **PC ローカル FastAPI サーバ（`127.0.0.1` のみ）+ 素の HTML/JS + Chart.js ローカル同梱**。既存 Python モジュール（db/google_health_client/publish/bmr/intake）を薄くラップ。`diet serve` 追加、CLI は併存。
- `orchestrator.py` の計算ロジックと click 対話 I/O を分離（Web/CLI 共用の純関数へ）。新規: `src/diet/web/{app.py,service.py,static/}`。
- API: `GET /api/day`・`/api/history`、`POST /api/sync`・`/api/intake`・`/api/weight`・`/api/publish`、`GET /api/auth/status`。当日状態 DTO 中心。
- **秘匿**: 食事 kcal/note は localhost ブラウザにのみ返す。publish は従来 `build_records_from_db`（5 フィールド allowlist）不変＝境界テスト有効。
- **OAuth (`diet auth`) は v1 では CLI 据え置き**（別ポート callback で複雑なため）。誤入力削除 `DELETE /api/intake/{id}` は MVP 外。

**次回**: Section 3（秘匿/エラー/テスト + **移行ライブ E2E との順序**）提示 → 承認 → spec 作成（`docs/superpowers/specs/`）→ spec review → writing-plans。※ Web UI の sync は未検証の Google Health 連携に依存するので、移行 E2E との前後関係を Section 3 で決める。

**運用学び**: ultracode の長い処理は **background 実行 + 各ステップ 1 行進捗報告 + タスクリスト更新**を既定に（前面・無音・長尺だと進捗不明で放置が起きる）。監視は `/workflows`・`Ctrl+O`(トランスクリプト)・`Ctrl+T`(タスクパネル)、割り込みは `Esc`。

### 2026-06-01 — Google Health API 移行 実装完了 (PR #1)

GA 確認（2026-03-24 ローンチ済み）→ 移行に着手。10 エージェント並列ワークフローで現行コード精読 + 公式ドキュメントから API 契約確定 → codex 第二意見 + ユーザー選択で 5 設計判断確定 → writing-plans（レビュアー承認）→ subagent-driven で 6 タスク実装（各タスク TDD + 2 段階レビュー + per-commit codex）。

**成果**: 9 commit (`4a510dc..5fd608f`)、159 tests green、`feat/fitbit-diet-cli` push 済み、**PR #1 作成（マージは E2E 保留）**。oauth.py=Google OAuth2/HTTP loopback、fitbit_client.py→google_health_client.py（dailyRollUp adapter）、DB 列改名+v1→v2 migration、calibrate 参照表示化、spec rev 10+README+E2E チェックリスト、`cryptography` 依存除去。

**レビューで捕捉・修正した重要バグ**: ① refresh 時 user_id が "me" に上書き（→`user_id=tok.user_id` 明示）② 体重サンプルの naive/aware datetime 比較 TypeError でその日の体重黙殺（→tz-aware UTC 正規化）③ codex P2: 同一暦日で古い体重が新値を上書き（→最新サンプル選択）。

---

## 5. 次回セッションのアジェンダ

### トラック A: ローカル Web UI 仕上げ（GCP 不要・実装は完了済み）

PR #2（`feat/local-web-ui` → `feat/fitbit-diet-cli`）。残作業:
1. 自宅 PC で `py -m uv run diet serve` → `http://127.0.0.1:8770` を開き、sync ボタン・食事入力（`+追加`/`=上書き`）・体重入力・収支表示・履歴グラフ・publish を目視確認。
2. 問題なければ PR #2 を `feat/fitbit-diet-cli` へ merge。
3. ※ sync の実 Google Health 連携はトラック B 未完なので、UI 上で sync を押すと認証エラー/警告になる想定（トラック B 完了後に通る）。

### トラック B: ライブ E2E 検証（PR #1 マージのブロッカー・GCP 認証情報が必要）

詳細手順は `docs/superpowers/plans/2026-06-01-google-health-api-e2e-checklist.md`。要点:

1. **GCP Console**: プロジェクト作成 → Google Health API 有効化 → OAuth 同意画面を **Production に publish** → テストユーザーに自分の Gmail 追加 → **Web application** OAuth クライアント作成 → redirect `http://localhost:8765/callback` 登録 → `.env` に `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` 記入
2. `py -m uv run diet auth` → ブラウザで認可（証明書警告なし）→ token 保存確認
3. `py -m uv run diet sync --days 3` → `data/diet.db` 確認（steps/active_energy/distance 入る、weight が 1000 倍でない＝grams→kg 正常）
4. **★ ASSUMED フィールドを実応答で確認**（§3）— 違えば adapter 1 行 + テスト 1 つ修正
5. Renpho 体重が Google Health に出るか確認
6. `py -m uv run diet` → HPasaneel publish → dashboard 確認、note/kcal 非漏洩確認
7. すべて OK → PR #1 を main へ merge

---

## 6. 重要な前提・制約

- 最終判断者は常に人間。AI は補助役
- `MEMORY.md` は 200 行上限、`MEMORY_PENDING.md` は post-commit hook 自動生成（hook 未 install のため現状は空）
- セッションサマリーは直近 3 件のみ保持
- Windows + Git Bash 環境、`uv` は `py -m uv run ...` で呼ぶ
- `tzdata` パッケージは Windows + Python 3.14 で ZoneInfo に必須（pyproject に追加済み）
- `.env` は gitignore 済み (Fitbit Client Secret はリポジトリに入れない)
- `data/diet.db` も gitignore 済み (食事ノートは絶対公開しない物理境界)
