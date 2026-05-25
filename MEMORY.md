# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `b4f49e7`（Phase 10 README + memory 同期）
最終更新日: 2026-05-26
GitHub: https://github.com/pcjidouka-spec/fitbit-diet (feat/fitbit-diet-cli)

★ **2026-05-26 重要: Fitbit Web API が Google Health API に移行中**。新規アプリ登録は dev.fitbit.com で停止、Google Cloud Console 経由に。古い Fitbit API は 2026-09 まで動くが、私たちは登録できない。**5 月末（2026-05-31 頃）の Google Health API 正式リリース後に移行作業**を行う方針で 1 週間保留。詳細は § 3 と § 5。

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
| Phase 10.2 (手動 E2E) | ⏸ **保留** (Fitbit API → Google Health API 移行待ち、~5/31 まで) | 5 月末以降に再開、§ 5 の手順参照 |
| Google Health API 移行 | ⏸ **保留中** (本リリース待ち) | spec rev 10 + oauth.py / fitbit_client.py の書き換え |
| PR / merge | 未実施 | 移行完了後に main へ merge |

---

## 3. 未解決の課題・保留事項

| 課題 | 優先度 | 備考 |
|------|--------|------|
| **Fitbit → Google Health API 移行** | **★ 高** | 旧 Fitbit Web API は 2026-09 非推奨、新規登録は既に閉鎖済み。Google Cloud Console 経由の Google Health API に置き換え必要。1 週間待って正式リリース後に着手 |
| Renpho → Fitbit → Google Health データ経路 | 中 | Renpho 同期は Fitbit アプリ側で従来通り。Google Health API が Fitbit データを吸い上げる構造なので、データ source 経路自体は不変の見込み（要検証） |
| OAuth redirect URI = `https://www.google.com` 推奨 | 中 | Google Cloud Console 標準は web app 型で `https://www.google.com` だが、Desktop app 型を選べば `http://localhost:8765/callback` も可。CLI 用に Desktop app 型で進める |
| テストモード refresh token 7 日期限 | 中 | Google Health API の公開ステータスが「テスト」だと refresh token が 7 日で失効。`diet auth` を週次で再実行する運用、または publish 「本番モード」へ昇格（要 OAuth 同意審査）|
| 計画書 plan rev5 line 655 の `has_avg` 旧コード | 低 | 実装は spec §4.5 通り fix 済み。plan ドキュメントだけ古い |
| recharts 推移依存に moderate/high vulnerability 3 件 | 低 | d3 系の既知問題。pre-existing |
| Phase 9 最終 commit `ce617f0` の codex review credit 不足 | 低 | 回帰テスト追加済み、内容は前 codex 指摘の直接対応 |

---

## 4. セッションサマリー

### 2026-05-26 — Fitbit API 移行発覚 → 1 週間保留

ユーザーが Fitbit dev portal で Personal アプリ登録しようとした時に「2026-09 非推奨、新規登録は Google Health API へ」の案内を発見。私たちの実装は完全に旧 API 前提だったため pivot 必要に。

**判断**: Google Health API の正式リリース（~2026-05-31）まで 1 週間待機。それまでは破壊的変更が起き得るため、今着手しても再修正コストが発生する。

**保留中の作業**:
- spec rev 10: OAuth/endpoint セクションを Google Health API に置き換え
- `oauth.py`: Google OAuth 2.0 へ書き換え（authorize/token URL、Desktop app 型 redirect、refresh token 7 日対応）
- `fitbit_client.py`: 名前変更 + Google Health API endpoint へ
- `.env`: `GOOGLE_CLIENT_ID/SECRET` に
- README + plan + spec の登録手順を全面書き直し

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

### 再開タイミング: 2026-05-31 以降（Google Health API 正式リリース後）

### 再開手順

1. **Google Health API のドキュメント確認** → エンドポイント・スコープ・OAuth 流量を spec rev 10 に反映
   - https://developers.google.com/health-api (推測 URL、本リリース後に確定)
   - Activity / steps / weight に該当する resource type を特定
2. **Google Cloud Console でプロジェクト + OAuth クライアント作成**
   - プロジェクト名: `Personal Diet CLI` 等
   - **OAuth クライアントタイプ: Desktop app**（CLI 用、localhost callback 可）
   - またはガイド推奨の「Web server + redirect `https://www.google.com`」で手動コード paste 方式
   - Google Health API を「API 有効化」、スコープ追加（activity/weight 系）
   - **テストユーザー** に自分の Gmail を追加
3. **`.env` 更新**
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8765/callback  # Desktop type
   ```
4. **コード移行**
   - spec rev 10 → codex 確認 → 実装更新
   - `oauth.py`: Google OAuth URL に書き換え、refresh token 7 日警告ロジック追加
   - `fitbit_client.py`: Google Health API endpoint・JSON 構造に対応
   - `cli_helpers.py` の sync ロジックを新 endpoint で書き直し
   - 既存テスト (httpx mock) を Google 用 URL に置換、boundary test は不変
5. **`diet init`** で初回認証、`diet calibrate` → `diet` で動作確認
6. (任意) **PR 作成 → main へ merge**

### 保留中の手動可能タスク

API 待ちでもできること:
- 体重: Renpho アプリで普通に計測してアプリ内で確認
- 食事 kcal: メモアプリで記録、または `diet weight 71.2` / `diet baseline 2000` 等の CLI コマンドはローカルで動く（Fitbit sync 抜きでも DB に書ける）
- 歩数: Fitbit アプリ / スマホで確認
- これらを 1 週間続けて、API 移行後に過去日 `diet --date YYYY-MM-DD` で記録を埋める運用も可

---

## 6. 重要な前提・制約

- 最終判断者は常に人間。AI は補助役
- `MEMORY.md` は 200 行上限、`MEMORY_PENDING.md` は post-commit hook 自動生成（hook 未 install のため現状は空）
- セッションサマリーは直近 3 件のみ保持
- Windows + Git Bash 環境、`uv` は `py -m uv run ...` で呼ぶ
- `tzdata` パッケージは Windows + Python 3.14 で ZoneInfo に必須（pyproject に追加済み）
- `.env` は gitignore 済み (Fitbit Client Secret はリポジトリに入れない)
- `data/diet.db` も gitignore 済み (食事ノートは絶対公開しない物理境界)
