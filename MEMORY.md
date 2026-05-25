# MEMORY.md — プロジェクト永続記憶ファイル

> このファイルは、セッションをまたいで引き継ぐべき情報を整理するための標準メモリーです。
> `MEMORY_PENDING.md` に蓄積された差分を、人間またはAIがこのファイルへ統合して使います。

最終同期コミット: `(未同期)`
最終更新日: 2026-05-07

---

## 1. 確定済み意思決定

| 決定事項 | 内容 | 決定日 | 参照ログ |
|---------|------|--------|----------|
| メモリー運用方式 | `MEMORY.md` を正本、`MEMORY_PENDING.md` を一時差分ログとして運用する | 2026-05-07 | 初期導入 |
| AIツール | Claude Code のみ（Cursor 不使用） | 2026-05-07 | 移行 |

---

## 2. 現在進行中のタスク

| タスク | ステータス | 次のアクション | 担当 |
|-------|-----------|----------------|------|
| （なし） | — | — | — |

---

## 3. 未解決の課題・保留事項

| 課題 | 優先度 | 備考 |
|------|--------|------|
| （なし） | — | — |

---

## 4. セッションサマリー

### 2026-05-07 — Migration
- Migrated from Cursor-based to Claude Code-native memory structure
- Replaced .cursor/rules/memory-management.mdc with CLAUDE.md
- Added .gitattributes for .ps1 CRLF and .githooks/post-commit LF enforcement

---

## 5. 次回セッションのアジェンダ

- [ ] プロジェクト固有の内容をセクション1〜3に追加する

---

## 6. 重要な前提・制約

- 最終判断者は常に人間であり、AI は補助役とする
- `MEMORY.md` は要約済みの生きた記憶（200行上限）、`MEMORY_PENDING.md` は未整理の差分ログとする
- セッションサマリーは直近3件のみ保持する
- グローバルメモリ（`~/.claude/projects/.../memory/`）との連携はしない
