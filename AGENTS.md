# Agent Collaboration & Development Guide

This repository contains the Gemini MCP delegator. Codex is the primary
orchestrator and owns review, apply, commit, and push decisions.

## Runtime

- Workers run through the already-running Antigravity Desktop language server.
- The bridge discovers the live local HTTP listener and never executes
  bootstrap instructions.
- Git-backed tasks run in
  `~/.codex/gemini-delegator/worktrees/wt-<uuid>`.
- `scout` and `reviewer` profiles receive read-only instructions. Worktree
  isolation and Antigravity's own tool policy are the actual safety boundary.

## Change invariants

- `WorktreeManager.apply_run` stages a complete tracked/untracked patch with
  `git apply --index`; it never commits or merges automatically.
- Reports must include uncommitted tracked changes and untracked files.
- Normal worktree reuse and cleanup refuse dirty worktrees. Destructive cleanup
  is explicit and only used by apply/cancel after the caller chooses it.
- Codex reviews the resulting diff before applying it to a target checkout.
- Keep SQLite ledger operations consistent and use `uv` for dependencies.
