# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `dc81315`（distance=millimetersSum 修正・全 ASSUMED 確定）
最終更新日: 2026-06-04
GitHub: https://github.com/pcjidouka-spec/fitbit-diet / **PR #1 (Google Health 移行 + Web UI) MERGED → main** / PR #2 (Web UI) MERGED。feat ブランチ削除済み。

★ **2026-06-04 トラック B 完全完了 — 移行 + Web UI が main 入り**（main=`317394e`、224 tests green）。ステップ 1〜7 全通過: auth/sync/ASSUMED 突合（**rollup ネストの重大バグ発見・修正** `value.<metric>`→`<camelCaseType>.<metric>`、live で total-calories=1538 確認）/Renpho 体重確認/`diet` フル + HPasaneel publish + **秘匿境界 live CONFIRMED**（log.json は 5 フィールドのみ）/PR #1 を main へ merge。周辺バグも修正（cp932 UTF-8、oauth timeout 300→600s、`diet doctor` 追加）。**移行プロジェクトは実質完了**。残課題は § 3（軽微）。

★ **2026-06-03 完了: ローカル Web UI（`diet serve`）+ PR #2 マージ済み**（211→224 tests）。毎日フローをブラウザ(`127.0.0.1`)で完結。秘匿境界・localhost セキュリティはレビュー済み + 全 code コミット codex clean。HTTP dogfood 全 PASS。残: 自宅 PC での実ブラウザ目視（Chart.js 描画。headless は Win app-control policy で不可）。

★ **2026-06-01 完了: Fitbit Web API → Google Health API v4 移行を実装完了**（9 commit, PR #1）。コードは **code-complete・ライブ E2E pending**。**main へのマージは GCP セットアップ後のライブ E2E 検証が通るまで保留**（ASSUMED フィールドは adapter に隔離、実 API で要確認）。ASSUMED 項目は § 3、E2E 手順は § 5 トラック B。注: PR #2 マージにより feat/fitbit-diet-cli は移行 + Web UI を両方含む（PR #1 は両方を main へ運ぶ）。

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
| Phase 10.2 ライブ E2E（トラック B） | ✅ **完了** (ステップ 1〜7、2026-06-04) | — |
| PR #1 (移行 + Web UI → main) | ✅ **MERGED**（main=`317394e`、feat 削除済み） | — |
| ローカル Web UI (毎日フロー) | ✅ **完了**（main 入り、224 tests） | 自宅 PC で実ブラウザ目視のみ残（§3、軽微） |
| PR #2 (Web UI) | ✅ **MERGED** (→ feat/fitbit-diet-cli) | — |

---

## 3. 未解決の課題・保留事項

| 課題 | 優先度 | 備考 |
|------|--------|------|
| **ライブ E2E** | ✅ 完了 | 2026-06-04 ステップ 1〜7 全通過。PR #1 main マージ済み |
| **ASSUMED フィールド** | ✅ 全確認済み | rollup ネスト `<camelCaseType>.<metric>`、steps.countSum / activeEnergyBurned.kcalSum / totalCalories.kcalSum（int64 は文字列）、distance は **`millimetersSum`(mm)** に修正（`dc81315`、当初 meterSum/m は誤り）、weightGrams / civil_time / identity も確認。歩数端末（Fitbit）連携で全 live 確認完了 |
| Renpho/Fitbit → Google Health 経路 | ✅ 確認済み | 体重（Renpho 70.5kg）+ 歩数/活動/距離（Fitbit 17663 歩 / 12.078km / 1933kcal）が流れている（2026-06-04） |
| recharts 依存に vulnerability 3 件 | 低 | d3 系の既知問題。pre-existing |
| `config.exercise_calorie_source` 列 | 低 | DEPRECATED・unused（active-energy 固定化後）。schema migration 回避のため列は保持、コメント明記済み |

---

## 4. セッションサマリー

### 2026-06-04 — トラック B ライブ E2E（ステップ 1〜5）+ rollup バグ修正

GCP セットアップ（ユーザー手動: Health API 有効化 / 同意画面 Production publish / Web OAuth クライアント + redirect `localhost:8765/callback`）→ `.env` 記入 → `diet doctor`（新規 preflight）で検証 → `diet auth` → `diet sync --days 3`。

**最大の成果（ステップ 4）**: dailyRollUp の値ネストが ASSUMED と違い、**`rollupDataPoints[0].value.<metric>` ではなく `rollupDataPoints[0].<camelCaseType>.<metric>`**（live で `totalCalories.kcalSum`=1538 を確認）。旧実装は全活動指標を silent に 0 化する重大バグだった → `_daily_rollup_value` に wrapper_key 追加で修正（`fa550d4`）。identity 実 user_id / weightGrams→kg / weight civil_time filter も CONFIRMED。**その後 Fitbit 歩数端末を連携 → steps=17663/active=1933 確認、さらに distance が `meterSum`(m) でなく `millimetersSum`(mm) と判明し再修正（`dc81315`、12.078km）。これで全 rollup ASSUMED 確定。** int64 系（countSum/millimetersSum）は JSON 文字列で届く点も判明。

**周辺バグ修正**: ① cp932 で日本語出力クラッシュ → `cli.py` stdout/stderr を UTF-8 化（`5d0d0fa`、cron sync 死亡を予防）② OAuth callback timeout 300→600s（未確認アプリ警告を読む間にタイムアウトし接続拒否になる UX バグ）③ `diet doctor` preflight 追加（`.env`/config/token 検証、redirect URI のポート/パス厳密化、`98a6bac`）。

**環境メモ**: ポート 8765 が過去 auth の残骸 pythonw に占有され `WinError 10013` → プロセス終了で解放。**Renpho→Google Health 体重経路は実体重 70.1/70.5 で動作確認**。**残: ステップ 6（`diet` フル + HPasaneel publish + 秘匿境界目視）+ 7（PR #1→main）**。

### 2026-06-03 — ローカル Web UI 実装完了（PR #2）

brainstorm 再開（Section 3 を codex consult 反映で承認: 独立・Web UI 先行 / 秘匿 / localhost 防御フルセット / エラー semantics）→ spec 作成（reviewer 初回 Approved）→ writing-plans（reviewer 指摘 1 ブロッカー修正後 Approved）→ subagent-driven で 12 タスク実装。

**成果**: `feat/local-web-ui` 13 commit (`a1f3deb..b72193b`)、**211 tests green**、PR #2 作成（base=feat/fitbit-diet-cli）。`diet serve` で FastAPI(`127.0.0.1`)+素HTML/JS+同梱Chart.js。新 `src/diet/web/{service,security,app}.py` + static/templates。`parse_kcal` を intake.py に切り出し CLI/Web 共用、`run_sync_async`→`SyncOutcome` 返却。

**秘匿/セキュリティ**: publish は `build_records_from_db` 不変（食事 kcal/note は localhost のみ・publish 非漏洩、SQL トレーステストで実証）。Host/Origin/CSRF/loopback 防御 + 特権ポート拒否 + textContent 描画(XSS 防止)。

**codex 主導で修正した堅牢化**: 部分 sync 失敗の可視化(SyncOutcome)、token 失効/不在の reauth 信号、publish 失敗の細分コード(publish_no_data/blocked/git_failed/schema_invalid)、ポート解析の例外封じ込め、date クエリの 422 検証。最終統合レビュー **Ship**。

**codex**: PR #2 の全 code コミットを review 済み＝**clean**（c69017a の P2×3+P3×1 は次コミット d6b68af で自己修正済みと確認）。再レビュー不要。

**QA (HTTP dogfood)**: browse.exe が Win app-control policy でブロック → 実 HTTP で全エンドポイントを dogfood（seed 済み一時 DB、CSRF/Origin/Host を実通過）。**全 PASS**: index/CSRF 注入・UI 要素 9 個・GET day/history/auth・bad Host→400・Origin/CSRF 欠如→403・intake +N/=N と bad→400・weight と 0→400・sync 無 token→401 reauth_required・days=0→422・publish(no remote)→409 publish_git_failed・不正 date→422。**未検証**: Chart.js 描画・JS DOM 更新（実機ブラウザ必須）。

**PR #2 は feat/fitbit-diet-cli へ merge 済み**（local/remote の feat/local-web-ui 削除済み）。**残**: ① 自宅 PC で実ブラウザ目視 ② sync の実 Google Health はトラック B（移行 E2E）依存。

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


## 5. 次回セッションのアジェンダ

> ▶ **移行 + Web UI は main 入り完了。大きな未着手タスクは無し。以下は任意・軽微。**

### 任意の残タスク（優先度低）

1. **Web UI ブラウザ目視**: 自宅 PC で `py -m uv run diet serve` → `http://127.0.0.1:8770` で Chart.js 描画・DOM 更新・トーストを目視（HTTP 層は検証済み）。歩数/距離データも入ったのでグラフが見栄えする。
2. **日次運用の定着**: 毎日 `diet`（CLI）または `diet serve`（Web）で sync→食事入力→publish。cron 化する場合は `diet sync` を Production token（refresh 7 日制限なし）で。**デスクトップに起動ショートカット作成済み**（`start-dashboard.bat`＝serve 別窓起動 + ブラウザ自動オープン、`%~dp0` で ASCII-only、`Desktop\ダイエットダッシュボード.lnk`）。
3. （任意）init プロンプト誤入力を防ぐ検証を `diet doctor` に追加してもよい（今回 `Enter（content/diet）` を文字通り入力する事故→ config 修正済み）。

> ASSUMED フィールドは全て live 確認済み（§3）。移行プロジェクトに残ブロッカーは無し。

---

## 6. 重要な前提・制約

- 最終判断者は常に人間。AI は補助役
- `MEMORY.md` は 200 行上限、`MEMORY_PENDING.md` は post-commit hook 自動生成（hook 未 install のため現状は空）
- セッションサマリーは直近 3 件のみ保持
- Windows + Git Bash 環境、`uv` は `py -m uv run ...` で呼ぶ
- `tzdata` パッケージは Windows + Python 3.14 で ZoneInfo に必須（pyproject に追加済み）
- `.env` は gitignore 済み (Fitbit Client Secret はリポジトリに入れない)
- `data/diet.db` も gitignore 済み (食事ノートは絶対公開しない物理境界)
