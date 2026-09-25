---
type: log
title: fitbit連動ダイエット の bd memory・harness memory・open 起票の棚卸し（2026-09-25）
---

# fitbit連動ダイエット の棚卸し（2026-09-25）

計画: `codexclaude併用構築/docs/plan/0018-phase3-rollout-runbook.md`（Task 3・組 B）。★行数: bd memory 0 ＋ harness memory 2 ＋ open 起票 0 ＝ 2。
データ: bd は `.beads` はあるがデータベースが空（`all.jsonl` が 0 バイト）で bd の行は 0 件。harness memory は `C:\code-snapshot\work\fitbit連動ダイエット\harness\`。

★採用先の語彙: `docs/knowledge/<slug>.md`（事実・教訓）／`docs/decisions/<slug>.md`（決定の記録）／`AGENTS.md`（いつも効いてほしい規範・1行）／`不採用`（理由1行）。open 起票は関連リンク（`related:`）か `nolink:`。
★移すときは本文をそのまま写し、書き直すのは冒頭の要約と注記だけ。原本は `docs/archive/harness-memory/` に残る。

## bd memory（0）

行 0 件（bd のデータベースが空）。

## harness memory（2）

| 出どころ | 要約 | 採用先 | 理由 | 例外 |
|---|---|---|---|---|
| `MEMORY.md` | 索引（ultracode-progress-visibility.md への1行リンクのみ） | 不採用 | 索引。移した文書は `docs/` で `rg` で引ける | |
| `ultracode-progress-visibility.md` | 長時間走る ultracode/workflow/subagent を可視化する運用（`run_in_background`・毎ステップの進捗報告・`/workflows`/`Ctrl+O`/`Ctrl+T`/`Esc` の案内）。2026-06-02 の本セッション（Google Health API 移行）で確立し「全プロジェクトに適用」と明記 | `AGENTS.md` | feedback 型でいつも効いてほしい規範（1行） | |

## open 起票（0）

行 0 件（bd のデータベースが空）。
