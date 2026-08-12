#!/usr/bin/env python3
"""
SessionStart hook — Stock Dashboard / Culling Engine.

Reads session_root_target.json (sitting next to this script) — a small state
file that the END of a previous session may have set, naming which directory
the NEXT session should be rooted in (e.g. a feature worktree). If the
session's current working directory doesn't already match that target,
injects a directive telling the model to call EnterWorktree(path=...)
immediately, before touching anything else.

Why this exists (2026-07-08): a fresh session opened in Trader App (this
folder) has no way to know it should actually be working in the
newsletter-ingestion worktree — CLAUDE.md/CONTEXT.md instruction text is
advisory only, not a guarantee, and a session confirmed this by reporting
already-fixed code as a "new bug" because it read Trader App's own stale
local files instead of entering the worktree. This hook does NOT guess intent
from conversation text (a SessionStart hook fires before the model has seen
any message, so it couldn't). The target is set EXPLICITLY by the outgoing
session's end-of-session documentation step — see CONTEXT.md's "Session
Documentation" section, "Session handoff: next-session root". If no target is
set, or the target already matches cwd, this is a silent no-op.

Exit code is always 0 — this hook never blocks a session, only adds context.
"""

import json
import os
import sys

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "session_root_target.json")
STATE_FILE = os.path.normpath(STATE_FILE)


def _is_same_or_within(path: str, root: str) -> bool:
    p = os.path.normcase(os.path.normpath(os.path.abspath(path)))
    r = os.path.normcase(os.path.normpath(os.path.abspath(root)))
    if p == r:
        return True
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:
        return False  # different drives


def main():
    # Read stdin defensively — SessionStart payload shape isn't load-bearing
    # here, we only need to know this hook fired; fail open on anything odd.
    try:
        sys.stdin.read()
    except Exception:
        pass

    if not os.path.isfile(STATE_FILE):
        sys.exit(0)  # no target configured — nothing to do

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)  # malformed state file should never block a session — fail open

    target = state.get("target")
    if not target:
        sys.exit(0)  # explicitly cleared — no redirect needed

    cwd = os.getcwd()
    if _is_same_or_within(cwd, target):
        sys.exit(0)  # already rooted correctly — no-op

    reason = state.get("reason", "")
    reason_clause = f" Reason: {reason}" if reason else ""
    message = (
        "SESSION ROOT REDIRECT (set by the previous session's end-of-session handoff): "
        f'before doing anything else — before reading any other file — call '
        f'EnterWorktree(path="{target}"). This session started rooted elsewhere, but '
        f'the last session marked "{target}" as where work should continue.{reason_clause} '
        "Do not proceed on any other file until this call completes."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
