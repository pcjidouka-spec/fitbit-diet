# Memory Management

- At the start of each session (first turn), read `MEMORY.md` to understand current state and decisions.
- If `MEMORY_PENDING.md` contains unprocessed content (commit hash is not "(未生成)"), notify the user in the first turn.
- When asked to update memory: read both files, merge `MEMORY_PENDING.md` into the appropriate sections of `MEMORY.md`, then reset `MEMORY_PENDING.md` to the initial template.
- Never delete entries from the `確定済み意思決定` section of `MEMORY.md` without an explicit reason from the user.
- Keep `MEMORY.md` under 200 lines. The `セッションサマリー` section keeps the last 3 entries only.
