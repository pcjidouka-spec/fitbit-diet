# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `5fd608f`（Google Health API 移行完了 + E2E チェックリスト）
最終更新日: 2026-06-01
GitHub: https://github.com/pcjidouka-spec/fitbit-diet (feat/fitbit-diet-cli) / PR #1

★ **2026-06-01 完了: Fitbit Web API → Google Health API v4 移行を実装完了**（9 commit, 159 tests green, PR #1）。Google Health API は GA 済み（2026-03-24 ローンチ）。コードは **code-complete・ライブ E2E pending**。**main へのマージは GCP セットアップ後のライブ E2E 検証が通るまで保留**（一部の Google レスポンスのフィールド名が ASSUMED で adapter に隔離済み、実 API で要確認）。次のアクションは § 5、ASSUMED 項目は § 3。

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
| Phase 10.2 ライブ E2E | ⏸ **pending** (GCP 認証情報が必要) | § 5 の E2E チェックリスト実行 |
| PR / merge | PR #1 作成済み・**マージ保留** | ライブ E2E 通過後に main へ merge |
| ローカル Web UI (毎日フロー) | 🧠 **brainstorm 中** (Section 1+2 承認, Section 3 + spec 未) | 次回: Section 3 → spec 作成 → writing-plans。詳細は § 4 (2026-06-02) |

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

### 2026-05-26 — Fitbit API 移行発覚 → 1 週間保留

ユーザーが Fitbit dev portal で Personal アプリ登録しようとした時に「2026-09 非推奨、新規登録は Google Health API へ」の案内を発見。私たちの実装は完全に旧 API 前提だったため pivot 必要に。

**判断**: Google Health API の正式リリース（~2026-05-31）まで 1 週間待機。それまでは破壊的変更が起き得るため、今着手しても再修正コストが発生する。

**保留中の作業**:
- spec rev 10: OAuth/endpoint セクションを Google Health API に置き換え
- `oauth.py`: Google OAuth 2.0 へ書き換え（authorize/token URL、Desktop app 型 redirect、refresh token 7 日対応）
- `fitbit_client.py`: 名前変更 + Google Health API endpoint へ
- `.env`: `GOOGLE_CLIENT_ID/SECRET` に
- README + plan + spec の登録手順を全面書き直し

---

## 5. 次回セッションのアジェンダ

次回は独立した 2 トラック。どちらからでも可。

### トラック A: ローカル Web UI brainstorm 再開（GCP 不要・いつでも可）

中断地点 = **Section 3**（秘匿/エラー/テスト + 移行 E2E との順序）から。承認済み設計は § 4 (2026-06-02)。Section 3 → spec 作成 → spec review → writing-plans → 実装。

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
