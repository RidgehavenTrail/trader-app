---
description: Run the session-end handoff checklist (SESSIONS.md + CONTEXT.md STATUS + rule/memory status)
---

Run the full **Session-End Checklist** (defined in the Repository `CONTEXT.md`
"Session-End Checklist" section) for this session. **Perform each step — do not just
list them.** Report what you changed at the end, and flag anything you could not verify.

1. **SESSIONS.md entry (always, even for a small session).** Append a new
   `## Session N — YYYY-MM-DD — <title>` entry at the TOP of the Repository `SESSIONS.md`
   (newest-first). Bump `N` from the current newest entry. Cover: what shipped, the key
   decisions and *why*, commit hashes / branch, and a **"LEFT STATE — what the next session
   must know"** block (unmerged branches, pending verifies, next actions).

2. **CONTEXT.md STATUS fact table (non-optional, ~30s).** Update the header block at the top
   of the Repository `CONTEXT.md`: bump `last_session`, flip any feature status that changed
   (e.g. `planned/spec → built`), refresh `next_up`, and move any resolved item out of
   `pending_fixes` (into a `resolved_fixes` line or delete). Keep it terse fact-table style —
   NO prose (prose belongs in SESSIONS.md).

3. **Renamed/retired a file this session?** Grep every `.claude/rules/*` frontmatter (and
   CONTEXT.md/CLAUDE.md) for the old name and fix stale references.

4. **A rule's status changed (planned → built, etc.)?** Update that rule file's own status
   line now, so it doesn't drift.

5. **Memory.** Update the relevant project memory file (the running "next-action" note) and
   its one-line `MEMORY.md` index entry so the state survives to the next session.

Note: SESSIONS.md and CONTEXT.md live in the Repository dir (`Claude Repository/Stock
Dashboard - Culling Engine/`), reachable from the main Trader App working dir. They are
plain docs — freely editable. Do not `git`-commit them unless the user asks.
