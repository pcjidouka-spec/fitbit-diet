# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `156bfa4`（Phase 3 Task 3.2 まで）
最終更新日: 2026-05-25

---

## 1. 確定済み意思決定

| 決定事項 | 内容 | 決定日 | 参照ログ |
|---------|------|--------|----------|
| メモリー運用方式 | `MEMORY.md` を正本、`MEMORY_PENDING.md` を一時差分ログとして運用 | 2026-05-07 | 初期導入 |
| AIツール | Claude Code のみ（Cursor 不使用） | 2026-05-07 | 移行 |
| アーキテクチャ | B 案 = 単一対話型 CLI `diet` で 5 ステップ完結（sync → 食事入力 → BMR → 収支 → publish） | 2026-05-25 | 設計 |
| 言語/環境 | Python 3.11+ / uv 管理 / `py -m uv run ...` で起動（Windows、uv は PATH 未通） | 2026-05-25 | 実装 |
| ユーザープロファイル | 生年月日 1979-12-01、身長 169cm、男性、Asia/Tokyo | 2026-05-25 | ヒアリング |
| BMR 計算式 | Mifflin-St Jeor: `10*weight + 6.25*169 - 5*age + 5` | 2026-05-25 | spec §3 |
| 食事カロリー取得 | CLI 手入力（`+追加` / `=上書き` / Enter=skip）、過去 14 日 complete day 平均で補完 | 2026-05-25 | spec §4.5 |
| Fitbit カロリー source | `summary.marginalCalories` をデフォルト（BMR 二重計上を回避）。`activities[].calories` は calibrate で選択肢 | 2026-05-25 | spec §4 |
| 体重取得 | Renpho → Fitbit 同期 → Fitbit API（Renpho 公式 API 無し） | 2026-05-25 | ヒアリング |
| プライバシー境界 | `intake_events.note`（メニュー名）が★最重要秘匿。kcal は dashboard 非公開だが逆算は許容 | 2026-05-25 | spec §1 |
| 公開先 | HPasaneel（Next.js + Cloudflare Pages）の `content/diet/log.json` → `app/diet/page.tsx` で recharts 描画、メインナビに掲載 | 2026-05-25 | spec §7 |
| OAuth callback | HTTPS 必須（Fitbit 公式ドキュメント確認）→ 自己署名証明書 + `https://localhost:8765/callback` | 2026-05-25 | spec §8.1 |
| codex 独立レビュー | commit 直後に `codex review --commit <SHA>` 自動実行。spec / plan も同様にループしてクリーン GO まで | 2026-05-25 | グローバル CLAUDE.md |
| 実装方式 | superpowers:subagent-driven-development（implementer + spec reviewer + code quality reviewer） | 2026-05-25 | グローバル CLAUDE.md |

---

## 2. 現在進行中のタスク

| タスク | ステータス | 次のアクション | 担当 |
|-------|-----------|----------------|------|
| Phase 3: OAuth | Task 3.1, 3.2 完了 / 3.3 未完了（API 529 で中断） | Task 3.3 (token exchange + refresh) を実装 | Claude |
| Phase 4-10 | 未着手 | Fitbit client / publish / CLI / orchestrator / HPasaneel / edge cases / README | Claude |

---

## 3. 未解決の課題・保留事項

| 課題 | 優先度 | 備考 |
|------|--------|------|
| 実装計画 plan rev5 vs 実装の整合性 | 低 | Task 1.6 の `has_avg` ロジック修正は実装側で済み、plan rev5 line 655 が古いまま。次回プラン改訂時に直す |
| Row 3 (`partial + baseline only`) ラベル分割 | 解決済み | 実装で `recorded_partial_high` に分岐済み（commit 8849a96） |
| HPasaneel 側 build/lint baseline 取得 | 中 | Phase 8 着手前に `cd C:/code/HPasaneel && npm run lint && npm run build` で baseline を取り、新規 warning 出さないことを確認 |
| Fitbit Developer App 登録 | 中 | ユーザー手動。spec § 8.1 の表に従う。Callback URL = `https://localhost:8765/callback`（HTTPS 必須） |
| Renpho → Fitbit 同期設定 | 中 | ユーザー手動。Renpho アプリ → 設定 → サードパーティ連携 → Fitbit |

---

## 4. セッションサマリー

### 2026-05-25 — Spec + Plan + 実装 Phase 0-3.2

**Spec (rev 1 → rev 9, codex 4 ラウンド)**: `docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`
- 食事 kcal の 7 ケース決定表、prophylaxis として override 日 = authoritative
- sample floor N≥3、半開窓 [target-14, target)、bootstrap baseline
- 公開境界 2 層 allowlist (DTO + JSON schema, additionalProperties:false 両層)
- OAuth は HTTPS callback + 自己署名証明書（Fitbit 公式が HTTPS 強制）

**Plan (rev 1 → rev 5, codex 4 ラウンド)**: `docs/superpowers/plans/2026-05-25-fitbit-diet-cli.md`
- 10 Phase / 52 タスク TDD 構成。最終 clean GO 取得（commit cbb2d67）

**実装 (feat/fitbit-diet-cli ブランチ)**: 6576035..156bfa4
- Phase 0: scaffold (uv + click + pytest) ✅
- Phase 1: bmr.py / intake.py 純粋関数群 ✅ (43 tests)
- Phase 2: db.py SQLite 層 ✅ (14 tests)
- Phase 3: oauth.py 自己署名証明書 (3.1) + auth URL/HTTPS callback (3.2) ✅ (4 tests)
- Phase 3.3: token exchange + refresh ❌ (API 529 で中断、次回継続)
- 合計 61 tests pass

### 2026-05-07 — Migration
- Migrated from Cursor-based to Claude Code-native memory structure
- Added .gitattributes for .ps1 CRLF and .githooks/post-commit LF enforcement

---

## 5. 次回セッションのアジェンダ

1. **Phase 3 Task 3.3** — `oauth.py` に `exchange_code_for_token` / `refresh_access_token` を実装（pytest-httpx mock テスト 3 件）→ commit
2. **Phase 4 (Fitbit client)** — `fitbit_client.py` 4 タスク（HTTP + activity / weight endpoint / rate limit / 401 refresh）
3. **Phase 5 (publish)** — `publish.py` 7 タスク（DTO + 2 段 JSON schema + boundary test + git ops）— ★ 公開境界の最重要部分
4. **Phase 6 (CLI)** — 8 コマンド（init / sync / calibrate / weight / baseline / show / auth / 引数なし default）
5. **Phase 7 (orchestrator + formatters)** — 5 ステップ対話フロー + 表示文字列
6. **Phase 8 (HPasaneel)** — recharts + `app/diet/page.tsx` (server) + `DietCharts.tsx` (client) + ナビ追加
7. **Phase 9 (edge cases)** — 11 テスト（sync 失敗 / 体重 fallback / cold start / dirty repo / push 失敗 / cert regen / refresh 失敗等）
8. **Phase 10 (README + 手動 E2E)** — README、Fitbit dev portal で本物のアプリ登録 → 初回 `diet init` 動作確認

実装方式は subagent-driven-development を継続。token 節約のため同一モジュールの隣接タスクは 1 implementer dispatch でバッチ。code quality + spec compliance を 1 reviewer で兼ねるパターンを採用 (Phase 2 で実証済み)。

---

## 6. 重要な前提・制約

- 最終判断者は常に人間であり、AI は補助役とする
- `MEMORY.md` は要約済みの生きた記憶（200行上限）、`MEMORY_PENDING.md` は未整理の差分ログとする
- セッションサマリーは直近3件のみ保持する
- グローバルメモリ（`~/.claude/projects/.../memory/`）との連携はしない
- post-commit hook (`.githooks/post-commit`) は手動 install 必要（`scripts/install-memory-hook.ps1`）。未 install のため MEMORY_PENDING は自動更新されない
- Windows + Git Bash 環境。`uv` は PATH 未登録 → `py -m uv run ...` で呼ぶ
