# Codex Gemini Delegator V2

A robust, production-ready MCP (Model Context Protocol) server that allows **OpenAI Codex to supervise and delegate tasks to Google Gemini (Antigravity) workers as subordinate agents**. 

Unlike other bridges, this delegator treats Gemini workers as resilient background jobs. It orchestrates isolated Git worktrees, enforces strict security boundaries, and connects to the already-running Antigravity language server.

## Key Features

1. **True Git Worktree Isolation**: When Codex delegates a task, the delegator automatically spawns an isolated worktree (`~/.codex/gemini-delegator/worktrees/wt-<uuid>`). Gemini executes its code changes strictly inside this isolated environment. Reports include uncommitted and untracked changes; applying a run stages them into a clean target without auto-committing.
2. **First-Party API Alignment**: This MCP server exposes the exact tool names and signatures expected by mainstream Codex delegators (`delegate_to_agent`, `apply_agent_run`, `get_agent_run_report`, etc.).
3. **Antigravity Language-Server Bridge**: Workers use the signed-in Antigravity Desktop language server. The bridge discovers its dynamic local port by validating the CSRF page instead of relying on a stale hard-coded port.
4. **Symlink-Resistant Security Boundaries**: Subordinate workers are hardened against path traversal and symlink vulnerabilities. A custom hook (`enforce_boundaries.py`) prevents them from executing destructive commands (`rm -rf`, `git reset`) and strictly jails their write access to their delegated scope.
5. **SQLite WAL Persistence**: All runs, PIDs, and logs are tracked in a lightning-fast SQLite WAL ledger. If you close your Codex session, the Gemini workers keep running in the background and their state is fully recoverable.

## Prerequisites

- [Google Antigravity (`gemini` CLI)](https://github.com/google/antigravity) installed globally.
- Python 3.10+
- Codex CLI (`codex`)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/psychofanplays/gemini4codex-mcp.git
   cd gemini4codex
   ```

2. **Register the MCP Server in Codex using `uv`:**
   Add the following to your `~/.codex/config.toml` (or equivalent Codex MCP configuration).
   We highly recommend using `uv` to automatically manage the environment and dependencies:
   ```toml
   [mcp.servers.gemini-delegator]
   command = "uv"
   args = [
       "--directory", 
       "/ABSOLUTE/PATH/TO/gemini4codex", 
       "run", 
       "-m",
       "server.gemini_delegator"
   ]
   ```

3. **No bootstrap command is required:** The MCP server does not execute bootstrap/setup instructions. `GEMINI.md` and Codex-side instructions remain policy references only.

## How It Works

When Codex is connected to the MCP server, it gains access to the following tools:

- `list_agent_backends`: Verifies the Gemini CLI and DB are healthy.
- `list_agent_runs`: Displays all active, idle, and failed background workers.
- `delegate_to_agent`: Spawns a new Gemini worker inside a new UUID Git Worktree.
- `continue_agent_run`: Sends a follow-up instruction to an existing worker.
- `get_agent_run_report`: Returns the worker's JSON logs, execution status, and the complete tracked/untracked diff from its worktree.
- `apply_agent_run`: Stages the worker's worktree patch into a clean target branch; it does not auto-commit.
- `cleanup_agent_run`: Cancels a running worker and deletes its isolated worktree.

## Example Workflow (From Codex's Perspective)

1. **Codex**: "I need to refactor the database schema, but I don't want to break the app. I'll delegate this to a Gemini worker."
2. **Codex** calls `delegate_to_agent(worker_id="db-refactor", workspace_path=".")`
3. **Delegator Server** creates `~/.codex/gemini-delegator/worktrees/wt-5f8a9b2c` and sends the task through the Antigravity language server.
4. **Gemini** works in the background, modifying files. Codex reviews the complete diff before applying it.
5. **Codex** periodically calls `get_agent_run_report("db-refactor")`. 
6. **Codex** reads the `git diff` returned by the report. "Looks good, the tests passed."
7. **Codex** calls `apply_agent_run("db-refactor")`.
8. **Delegator Server** stages the changes into the main branch but explicitly leaves them uncommitted, allowing Codex or the human user to review and finalize the commit.

## Security

This plugin aggressively restricts the Gemini subordinate worker:
- **True OS Sandboxing**: The Delegator explicitly prevents subordinate workers from bypassing the Antigravity OS sandbox, meaning they are natively isolated from the filesystem at the kernel level and cannot modify files outside the delegated scope.
- **Git Sandboxing**: Workers are forbidden from running structural git commands (`git commit`, `git push`, `git merge`) or destructive operations (`rm -rf`).
- **Profile Segregation**: You can delegate a `scout` or `reviewer` profile, which disables all write tools completely.

## Architecture Map

The project is structured into three main layers:

```
gemini4codex/
├── pyproject.toml           # Python packaging and dependency config
├── Codex-BOOTSTRAP.md       # Optional historical/reference guidance; never executed by the server
└── server/
    ├── gemini_delegator.py  # The FastMCP Server exposing endpoints to Codex
    ├── agentapi.py           # Antigravity language-server bridge and port discovery
    ├── supervisor.py         # Async execution engine and ledger integration
    ├── worktree.py           # Git worktree isolation and patch staging
    ├── security.py          # Dynamic SDK hooks to jail the worker
    └── ledger.py            # SQLite WAL state manager for robust persistence
```

- **Layer 1: The Codex Interface** (`gemini_delegator.py`) handles all incoming MCP requests.
- **Layer 2: The Orchestrator** (`worktree.py` & `supervisor.py`) spins up the isolated environment and runs the worker asynchronously through the Antigravity language server.
- **Layer 3: The Jailed Subordinate** (`security.py`) restricts the worker's context natively so it cannot harm the host system or primary branch.
