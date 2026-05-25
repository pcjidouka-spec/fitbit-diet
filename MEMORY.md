# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `d1014cf`（Phase 10 README まで）
最終更新日: 2026-05-25
GitHub: https://github.com/pcjidouka-spec/fitbit-diet (feat/fitbit-diet-cli)

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

---

## 2. 現在進行中のタスク

| タスク | ステータス | 次のアクション |
|-------|-----------|----------------|
| Phase 0-9 + 10.1 | ✅ 完了 (全 159 tests pass、HPasaneel dashboard 公開済み) | — |
| Phase 10.2 (手動 E2E) | ⏳ user 手動作業 | Fitbit dev portal でアプリ登録 → `.env` 記入 → `uv tool install .` → `diet init` |
| PR / merge | 未実施 | feat/fitbit-diet-cli を main に merge（`gh pr create` または直 merge） |

---

## 3. 未解決の課題・保留事項

| 課題 | 優先度 | 備考 |
|------|--------|------|
| 計画書 plan rev5 line 655 の `has_avg` 旧コード | 低 | 実装は spec §4.5 通り fix 済み。plan ドキュメントだけ古い、次回改訂時に揃える |
| recharts 推移依存に moderate/high vulnerability 3 件 | 中 | d3 系の既知問題。`npm audit fix --force` は API 破壊リスクあり、現状は受容 |
| Phase 9 最終 commit `ce617f0` の codex review credit 不足 | 低 | network-level refresh transient エラーの fix。回帰テスト追加済み、内容は前 codex 指摘の直接対応 |
| Fitbit Developer App 登録 | 高 | ユーザー手動。spec §8.1 表に従う。Callback = `https://localhost:8765/callback` |
| Renpho → Fitbit 同期設定 | 高 | ユーザー手動。Renpho アプリ → 設定 → サードパーティ連携 → Fitbit |
| `diet init` 実機初回起動 | 高 | `.env` 設定後、`py -m uv tool install .` → `diet init` で対話実行 |

---

## 4. セッションサマリー

### 2026-05-25 — 全 Phase 完了 (159 tests, dashboard 公開)

**Spec rev 1→9 / Plan rev 1→5** いずれも codex 4 ラウンドで clean GO 取得 (`docs/superpowers/`)

**実装** (`feat/fitbit-diet-cli` ブランチ, commit `6576035..d1014cf`)
- Phase 0: scaffold (uv + click + pytest) ✅
- Phase 1: bmr.py / intake.py 純粋関数 (7-case decision、=0 断食保護) ✅
- Phase 2: db.py SQLite (atomic token rotation、note 構造的隔離) ✅
- Phase 3: oauth.py (自己署名証明書、HTTPS callback、token exchange/refresh) ✅
- Phase 4: fitbit_client.py (rate limit 追跡、401 自動 refresh) ✅
- Phase 5: publish.py (DTO + JSON schema 2 段 validate + boundary test、note 漏洩構造的不可) ✅
- Phase 6: 8 CLI コマンド (init/sync/calibrate/weight/baseline/show/auth/default) ✅
- Phase 7: orchestrator + formatters (5 ステップ対話 + 7 label 表示) ✅
- Phase 8: HPasaneel dashboard (recharts client + server page + ナビ) ✅ → push 済み
- Phase 9: 11 エッジケース統合テスト (sync 失敗 / weight fallback / rev N / 429 / 並列 token / cold start / dirty repo / push 失敗 / cert regen / refresh 失敗) ✅
- Phase 10.1: README ✅

**最終状態**: `py -m uv run pytest -q` → **159 passed**。GitHub push 済み。

### 2026-05-07 — Migration (Cursor → Claude Code)

---

## 5. 次回セッションのアジェンダ

1. **Fitbit dev portal でアプリ登録** (ユーザー手動、spec §8.1 表参照)
2. **`.env` に Client ID/Secret 記入** (cp `.env.example` `.env` → 編集)
3. **`py -m uv tool install .`** で global に diet コマンド配置
4. **`diet init`** → 生年月日/身長/性別/HPasaneel パス/baseline 入力 → ブラウザで Fitbit 認証 (証明書警告は Proceed)
5. **`diet calibrate`** → `marginal` を選択
6. **`diet`** で初回対話実行、食事 `=2300` 等で記録、`y` で publish
7. **HPasaneel `/diet` 確認** → https://asaneel.jp/diet (Cloudflare deploy 後)
8. (任意) **PR 作成 → main へ merge**

---

## 6. 重要な前提・制約

- 最終判断者は常に人間。AI は補助役
- `MEMORY.md` は 200 行上限、`MEMORY_PENDING.md` は post-commit hook 自動生成（hook 未 install のため現状は空）
- セッションサマリーは直近 3 件のみ保持
- Windows + Git Bash 環境、`uv` は `py -m uv run ...` で呼ぶ
- `tzdata` パッケージは Windows + Python 3.14 で ZoneInfo に必須（pyproject に追加済み）
- `.env` は gitignore 済み (Fitbit Client Secret はリポジトリに入れない)
- `data/diet.db` も gitignore 済み (食事ノートは絶対公開しない物理境界)
