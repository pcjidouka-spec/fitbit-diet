## 知識とタスク（docs 方式）

- 知識とタスクは `docs/` に置く（設計: `codexclaude併用構築/docs/plan/0002-knowledge-task-architecture.md`）。事実は `docs/knowledge/`、決定は `docs/decisions/`、やることは `docs/tasks/`（`task_status: open` / `done`）、経緯は `docs/log/`
- ★このリポジトリでは bd を使わない（`.beads` は最後の削除工程まで残すが、読み書きしない）
- 文書の frontmatter とリンクの規則は `codexclaude併用構築/AGENTS.md` と同じ。検査: `py C:/code/codexclaude併用構築/scripts/check_docs.py .`
- 長時間走る ultracode/workflow/subagent は `run_in_background` と毎ステップの進捗報告で可視化する（`/workflows`・`Ctrl+O`・`Ctrl+T`・`Esc` で監視）。全プロジェクト共通の運用
