# Codex Gemini Delegator Guide

Codex is the primary orchestrator. Gemini workers are subordinate background
workers; Codex owns review, apply, commit, and push decisions.

Workers are sent through the already-running Antigravity Desktop language
server by `server/agentapi.py`. That adapter discovers the live local listener,
resolves friendly model names to currently advertised IDs, starts an Agent API
cascade, and waits for the final trajectory response. It does not construct
the retired `LocalAgentConfig` SDK path and it never executes bootstrap
instructions.

Git-backed tasks use isolated worktrees at
`~/.codex/gemini-delegator/worktrees/wt-<uuid>`. The report includes tracked
and untracked changes. Applying a run stages the complete patch with
`git apply --index` and leaves review and commit ownership with Codex.

`scout` and `reviewer` profiles add read-only instructions. They are not a
replacement for Antigravity's own tool policy; worktree isolation remains the
primary protection for the target checkout.

Use `uv` for dependencies and preserve the SQLite ledger's WAL behavior.
