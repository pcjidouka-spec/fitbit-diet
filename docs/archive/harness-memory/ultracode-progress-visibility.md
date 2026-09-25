---
name: ultracode-progress-visibility
description: Keep long ultracode/workflow/subagent runs observable so the user never leaves them idle wondering if they stalled
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0361bd50-f3d6-4aaf-8020-6baec3afaff8
---

In ultracode sessions the user repeatedly lost track of whether a long run was still progressing or had stalled, and risked leaving it idle. Root cause was MY pattern: dispatching long **foreground** subagents (each running for minutes) with no interim output, so the session went silent.

**Why:** A foreground subagent/command blocks the session and only surfaces its final result — during the minutes it runs there is no visible movement, which reads identically to "hung." The user can't distinguish working from stalled.

**How to apply:**
- Default long/expensive phases to **`run_in_background: true`** (Agent/Bash) or the Workflow tool — these keep the session responsive, emit a completion `task-notification`, and are visible live via `/workflows`.
- Emit a **one-line progress report after every step** (and split very long single agents into smaller reported chunks) so there is steady movement.
- Keep the **task list updated** (TaskCreate/TaskUpdate `activeForm`) so the spinner/task panel reflects current work.
- For very long runs, agree on a checkpoint cadence up front.
- Tell the user the monitoring affordances: `/workflows` (live workflow tree; `p` pause, `x` stop, `r` restart), `Ctrl+O` (transcript — truest "is it doing anything" signal: are tool calls still appearing?), `Ctrl+T` (background task panel), `Esc` once to interrupt and ask status without losing work.

Established 2026-06-02 (fitbit-diet Google Health migration session — long foreground subagent chain triggered the complaint). Applies to all projects, not just this one.
