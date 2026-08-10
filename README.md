# Codex Gemini Delegator V2

A robust, production-ready MCP (Model Context Protocol) server that allows **OpenAI Codex to supervise and delegate tasks to Google Gemini (Antigravity) workers as subordinate agents**. 

Unlike other bridges, this delegator treats Gemini workers as resilient background jobs. It orchestrates isolated Git worktrees, enforces strict security boundaries, monitors stream-json for infinite loop failures, and auto-nudges stuck workers to unblock them.

## Key Features

1. **True Git Worktree Isolation**: When Codex delegates a task, the delegator automatically spawns an invisible Git worktree (`.worktrees/wt-<uuid>`). Gemini executes its code changes strictly inside this isolated environment. Your main branch remains completely untouched until Codex explicitly applies the run.
2. **First-Party API Alignment**: This MCP server exposes the exact tool names and signatures expected by mainstream Codex delegators (`delegate_to_agent`, `apply_agent_run`, `get_agent_run_report`, etc.).
3. **Loop Detection & Auto-Nudging**: Built-in state heuristics actively monitor the `stream-json` output of the Gemini worker. If the worker gets stuck in an infinite tool failure loop or tries the exact same broken command 3 times in a row, the Supervisor forcefully restarts it with a recursive `--session-id` and a strict system nudge to change strategies.
4. **Symlink-Resistant Security Boundaries**: Subordinate workers are hardened against path traversal and symlink vulnerabilities. A custom hook (`enforce_boundaries.py`) prevents them from executing destructive commands (`rm -rf`, `git reset`) and strictly jails their write access to their delegated scope.
5. **SQLite WAL Persistence**: All runs, PIDs, and logs are tracked in a lightning-fast SQLite WAL ledger. If you close your Codex session, the Gemini workers keep running in the background and their state is fully recoverable.

## Prerequisites

- [Google Antigravity (`agy` / `gemini`)](https://github.com/google/antigravity) installed globally.
- Python 3.9+
- Codex CLI (`codex`)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/gemini4codex.git
   cd gemini4codex
   ```

2. **Run the Installer script:**
   ```bash
   ./scripts/install.sh
   ```
   This will install the Python dependencies and copy the security hooks to your `~/.gemini/config/plugins/codex-supervised-worker` directory.

3. **Register the MCP Server in Codex:**
   Add the following to your `~/.codex/config.toml`:
   ```toml
   [mcp.servers.gemini-delegator]
   command = "python3"
   args = ["/path/to/gemini4codex/server/gemini_delegator.py"]
   ```

4. **Verify Installation:**
   ```bash
   ./scripts/doctor.sh
   ```

## How It Works

When Codex is connected to the MCP server, it gains access to the following tools:

- `list_agent_backends`: Verifies the Gemini CLI and DB are healthy.
- `list_agent_runs`: Displays all active, idle, and failed background workers.
- `delegate_to_agent`: Spawns a new Gemini worker inside a new UUID Git Worktree.
- `continue_agent_run`: Sends a follow-up instruction to an existing worker.
- `get_agent_run_report`: Returns the worker's JSON logs, execution status, and importantly, the **raw Git diff** of what the worker changed inside its worktree.
- `apply_agent_run`: Performs a squash merge of the worker's temporary worktree into your main branch.
- `cleanup_agent_run`: Cancels a running worker and deletes its isolated worktree.

## Example Workflow (From Codex's Perspective)

1. **Codex**: "I need to refactor the database schema, but I don't want to break the app. I'll delegate this to a Gemini worker."
2. **Codex** calls `delegate_to_agent(worker_id="db-refactor", workspace_path=".")`
3. **Delegator Server** creates `.worktrees/wt-5f8a9b2c` and spawns `gemini -p ...` inside it.
4. **Gemini** works in the background, modifying files. If it loops or gets stuck, the Supervisor auto-nudges it.
5. **Codex** periodically calls `get_agent_run_report("db-refactor")`. 
6. **Codex** reads the `git diff` returned by the report. "Looks good, the tests passed."
7. **Codex** calls `apply_agent_run("db-refactor")`.
8. **Delegator Server** squash merges the changes cleanly into the main branch.

## Uninstallation

To remove the security plugins and SQLite ledger:
```bash
./scripts/uninstall.sh
```

## Security

This plugin aggressively restricts the Gemini subordinate worker:
- **Write Jailing**: If a worker is delegated to `./src/frontend`, any attempt to `write_to_file` in `./src/backend` is instantly rejected.
- **Git Sandboxing**: Workers are forbidden from running structural git commands (`git commit`, `git push`, `git merge`).
- **Profile Segregation**: You can delegate a `scout` or `reviewer` profile, which disables all write tools completely.

## Architecture Map

The project is structured into three main layers:

```
gemini4codex/
├── server/
│   ├── gemini_delegator.py  # The FastMCP Server exposing endpoints to Codex
│   ├── supervisor.py        # Async execution engine; parses stream-json & detects loops
│   ├── worktree.py          # Git worktree isolation and squash-merge orchestrator
│   └── ledger.py            # SQLite WAL state manager for robust persistence
├── plugin/
│   └── skills/
│       └── delegate-to-gemini/
│           └── SKILL.md     # Codex-side documentation on how to use these MCP tools
├── antigravity-plugin/
│   └── hooks/
│       └── enforce_boundaries.py  # Security hook injected into the worker to prevent sandbox escapes
└── scripts/
    ├── install.sh           # Local setup and plugin deployment
    ├── uninstall.sh         # Cleanup script
    └── doctor.sh            # Health check utility
```

- **Layer 1: The Codex Interface** (`gemini_delegator.py`) handles all incoming MCP requests.
- **Layer 2: The Orchestrator** (`worktree.py` & `supervisor.py`) spins up the isolated environment and runs the process asynchronously.
- **Layer 3: The Jailed Subordinate** (`enforce_boundaries.py`) runs in a restricted context where it cannot harm the host system or primary branch.
