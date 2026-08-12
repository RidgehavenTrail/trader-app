#!/usr/bin/env python3
"""
PreToolUse + PostToolUse hook for Claude Code — Stock Dashboard / Culling Engine.

Registered on BOTH events for Edit/Write/MultiEdit (see settings.json):

PreToolUse:
1. BLOCK the edit if the new content contains what looks like a literal
   API key (instead of an env-var lookup).
2. SNAPSHOT: before the edit lands, copy the CURRENT (pre-edit) version of
   the file into the Repository folder as a timestamped rollback point.

PostToolUse:
3. SYNC: after the edit lands, overwrite the plain (non-timestamped)
   Repository mirror with the file's NEW on-disk content.

Why both: a PreToolUse-only mirror copies pre-edit state, so within a
session where a file is edited N times, only edits 1..N-1 ever get pushed to
the plain mirror — the FINAL edit is never followed by another PreToolUse
call, so it's silently never synced. Confirmed 2026-07-08: every file edited
more than once in one session (newsletter_ingest.py, watchtower.html,
settings.json, newsletter-ingestion.md) had its last edit missing from
Repository, which is exactly what made a fresh session look like it "didn't
know about" work that had actually landed. The PostToolUse pass closes that
gap by re-syncing after every single edit, including the last one.

Exit code 0  -> allow the tool call (PreToolUse) / no-op (PostToolUse)
Exit code 2  -> block the tool call (PreToolUse only; stderr shown to user)

NOTE: paths below are hardcoded for this project's known layout. Adjust
LIVE_ROOT / REPO_ROOT if either directory ever moves.
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime

LIVE_ROOT = r"C:\Users\pguth\OneDrive\Desktop\Trader App"
REPO_ROOT = r"C:\Users\pguth\OneDrive\Desktop\Claude Repository\Stock Dashboard - Culling Engine"

# Also cover the newsletter-ingestion worktree as a "live" root, since it's
# a sibling working copy that should mirror to the same Repository folder.
WORKTREE_ROOT = r"C:\Users\pguth\OneDrive\Desktop\Trader App - newsletter-ingestion"

LIVE_ROOTS = [LIVE_ROOT, WORKTREE_ROOT]

# Relative paths (forward-slash form) that are KNOWN to genuinely diverge
# between LIVE_ROOT and WORKTREE_ROOT — not accidents, but two intentionally
# separate working copies of the same filename (e.g. watchtower.html is
# actively developed in the worktree while Trader App's copy is a stale
# pre-feature original; .env/CLAUDE.md/settings.json differ on purpose per
# location — port 5000 vs 5001, worktree-specific hook paths, etc.).
# Confirmed 2026-07-08: without namespacing, BOTH roots' copies of these
# files mapped to the exact same Repository path, so editing one silently
# clobbered whichever the other root had last mirrored there — with no
# error, no warning. Any relpath in this set gets its own subfolder under
# Repository when it comes from a NAMESPACED_ROOTS root (below), instead of
# landing at the same shared path LIVE_ROOT's copy uses.
NAMESPACED_RELPATHS = {
    "watchtower.html",
    "CLAUDE.md",
    ".env",
    ".env.example",
    ".claude/settings.json",
    ".claude/settings.local.json",
    # Trader-App-specific SessionStart redirect state (added 2026-07-08) — this
    # is inherently a Trader-App-only concept (the ambiguous default root
    # deciding whether to redirect elsewhere); a worktree copy would just be
    # inert clutter no hook ever reads, so never cross-propagate it.
    ".claude/session_root_target.json",
}

# Live roots (besides the primary LIVE_ROOT) whose divergent files (per
# NAMESPACED_RELPATHS) get mirrored under their own Repository subfolder,
# keyed by root -> subfolder name.
NAMESPACED_ROOTS = {
    WORKTREE_ROOT: "worktrees/newsletter-ingestion",
}

# Known placeholder strings that are fine to see literally in source.
ALLOWED_PLACEHOLDERS = {
    "YOUR_ANTHROPIC_API_KEY_HERE",
    "YOUR_ALPHA_VANTAGE_KEY_HERE",
}

# Patterns that suggest a real hardcoded secret. Deliberately a bit broad —
# false positives just mean an extra confirmation, false negatives leak a key.
KEY_PATTERNS = [
    re.compile(r'ANTHROPIC_API_KEY\s*=\s*["\'](sk-[^"\']+)["\']'),
    re.compile(r'ALPHA_VANTAGE_KEY\s*=\s*["\']([A-Z0-9]{10,})["\']'),
    re.compile(r'["\'](sk-ant-[A-Za-z0-9\-_]{20,})["\']'),  # bare Anthropic key literal
]


def find_hardcoded_keys(text: str):
    hits = []
    for pattern in KEY_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(1) if m.groups() else m.group(0)
            if value in ALLOWED_PLACEHOLDERS:
                continue
            hits.append(value)
    return hits


def _is_within(path: str, root: str) -> bool:
    """True only if `path` is genuinely inside `root`, compared component-wise
    (not by string prefix). This is what stops the live root "Trader App" from
    falsely matching the worktree "Trader App - newsletter-ingestion"."""
    p = os.path.normcase(os.path.normpath(os.path.abspath(path)))
    r = os.path.normcase(os.path.normpath(os.path.abspath(root)))
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:
        return False  # different drives


def _find_source_root(live_path: str):
    """Return (root, rel) for whichever LIVE_ROOT contains live_path — longest
    root first + real containment check, so a worktree path whose folder name
    merely *starts with* the live root's name can't be shadowed (the old
    str.startswith check mirrored worktree edits to a bogus "Claude
    Repository\\Trader App - newsletter-ingestion\\" sibling folder). Returns
    (None, None) if live_path isn't under any tracked root."""
    norm = os.path.normpath(os.path.abspath(live_path))
    for root in sorted(LIVE_ROOTS, key=len, reverse=True):
        root_norm = os.path.normpath(os.path.abspath(root))
        if _is_within(norm, root_norm):
            return root, os.path.relpath(norm, root_norm)
    return None, None


def map_to_repo_path(live_path: str):
    """Map a Trader App (or worktree) path to its Repository mirror path.

    Files in NAMESPACED_RELPATHS get their own subfolder under Repository when
    they come from a root listed in NAMESPACED_ROOTS — this is what stops e.g.
    the worktree's actively-diverged watchtower.html from colliding with
    Trader App's stale original at the same shared path (confirmed bug,
    2026-07-08). Everything else (docs meant to be identical everywhere, and
    locked-subsystem files nobody edits from the worktree) keeps the original
    single shared-path mapping.
    """
    root, rel = _find_source_root(live_path)
    if root is None:
        return None
    rel_forward = rel.replace("\\", "/")
    namespace = NAMESPACED_ROOTS.get(root)
    if namespace and rel_forward in NAMESPACED_RELPATHS:
        repo_path = os.path.normpath(os.path.join(REPO_ROOT, namespace, rel))
    else:
        repo_path = os.path.normpath(os.path.join(REPO_ROOT, rel))
    # Safety net: the mirror must never resolve outside REPO_ROOT.
    if _is_within(repo_path, os.path.normpath(os.path.abspath(REPO_ROOT))):
        return repo_path
    return None


def sync_to_sibling_roots(live_path: str):
    """PostToolUse: for a file meant to be identical everywhere (i.e. NOT in
    NAMESPACED_RELPATHS), copy the just-edited content directly to every OTHER
    live root's copy at the same relative path — not just to Repository.

    Closes a gap confirmed 2026-07-08: the hook only ever automated
    live-root -> Repository sync. Nothing automated Repository -> Trader App
    or worktree -> Trader App, so Trader App's own local copy of
    newsletter-ingestion.md silently drifted 42 lines behind the worktree's —
    the "copy to the matching path in the other directory" step from the
    Documentation Architecture convention depended on a human/session
    remembering to do it manually, and that step was missed. A fresh session
    rooted in Trader App then auto-loaded ITS OWN stale local rules file
    (path-scoped rules load from wherever Claude Code is rooted, not from
    Repository), reporting completed work as "not yet implemented."
    """
    root, rel = _find_source_root(live_path)
    if root is None:
        return
    rel_forward = rel.replace("\\", "/")
    if rel_forward in NAMESPACED_RELPATHS:
        return  # meant to diverge per root — never cross-propagate these
    for other_root in LIVE_ROOTS:
        if os.path.normpath(os.path.abspath(other_root)) == os.path.normpath(os.path.abspath(root)):
            continue
        if not os.path.isdir(other_root):
            continue
        dest = os.path.normpath(os.path.join(other_root, rel))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(live_path, dest)


def _resolve_repo_path(live_path: str):
    """Shared guard: map live_path to its Repository mirror, warning loudly
    (never silently) if an in-project file can't be mapped."""
    if not os.path.isfile(live_path):
        return None  # new file being created — nothing to snapshot/sync yet

    repo_path = map_to_repo_path(live_path)
    if repo_path is None:
        # Skip silently for genuinely out-of-project files (e.g. temp files),
        # but NEVER fail silently for a file that lives under a tracked root —
        # that silence is exactly what hid the worktree-mirroring bug.
        if any(_is_within(live_path, r) for r in LIVE_ROOTS):
            print(f"WARNING: pre_edit_guard could not map an in-project file to "
                  f"a Repository mirror path; edit NOT backed up: {live_path}",
                  file=sys.stderr)
        return None
    return repo_path


def snapshot_before_edit(live_path: str):
    """PreToolUse: copy the CURRENT (pre-edit) on-disk version to the
    Repository mirror, both as the plain rollback point and a dated snapshot.
    NOTE: this alone is not sufficient — see sync_after_edit()."""
    repo_path = _resolve_repo_path(live_path)
    if repo_path is None:
        return

    repo_dir = os.path.dirname(repo_path)
    os.makedirs(repo_dir, exist_ok=True)

    # Plain mirror copy (overwrites — this is a rollback point of the PRE-edit state).
    shutil.copy2(live_path, repo_path)

    # Dated snapshot alongside it so same-day multiple edits don't clobber
    # each other's rollback point.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base, ext = os.path.splitext(repo_path)
    snapshot_path = f"{base}.{stamp}{ext}"
    shutil.copy2(live_path, snapshot_path)


def sync_after_edit(live_path: str):
    """PostToolUse: overwrite the plain Repository mirror with the file's NEW
    (post-edit) on-disk content, AND (for shared, non-namespaced files) copy
    it directly to every sibling live root too — see sync_to_sibling_roots().
    This is what keeps everything current even after the LAST edit in a
    multi-edit sequence to the same file — the snapshot_before_edit() call for
    that edit only captured the PRIOR state."""
    if not os.path.isfile(live_path):
        return
    repo_path = _resolve_repo_path(live_path)
    if repo_path is not None:
        repo_dir = os.path.dirname(repo_path)
        os.makedirs(repo_dir, exist_ok=True)
        shutil.copy2(live_path, repo_path)
    sync_to_sibling_roots(live_path)


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # If we can't parse it, fail open rather than blocking all edits.
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool_name not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    # PostToolUse payloads include "tool_response"; PreToolUse payloads don't.
    is_post = "tool_response" in payload

    if is_post:
        # --- PostToolUse: sync the mirror to the file's new (post-edit) state ---
        if file_path:
            try:
                sync_after_edit(file_path)
            except Exception as e:
                print(f"WARNING: post-edit mirror sync failed for {file_path}: {e}", file=sys.stderr)
        sys.exit(0)

    # --- PreToolUse below ---

    # Content to scan for hardcoded keys: covers Write's `content` and
    # Edit's `new_string` — check whichever is present.
    content_to_scan = tool_input.get("content") or tool_input.get("new_string") or ""

    # --- Check 1: hardcoded key block ---
    hits = find_hardcoded_keys(content_to_scan)
    if hits:
        print(
            "BLOCKED: this edit appears to write a literal API key into "
            f"{file_path}. Use os.environ.get(...) with python-dotenv's "
            "load_dotenv() instead. Matched value(s) redacted: "
            + ", ".join(h[:6] + "..." for h in hits),
            file=sys.stderr,
        )
        sys.exit(2)

    # --- Check 2: snapshot the pre-edit state to Repository as a rollback point ---
    if file_path:
        try:
            snapshot_before_edit(file_path)
        except Exception as e:
            # Don't block the edit over a mirror failure, but make it visible.
            print(f"WARNING: rollback snapshot failed for {file_path}: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
