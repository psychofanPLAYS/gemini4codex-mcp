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

## Installation & Bootstrapping

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
       "server/gemini_delegator.py"
   ]
   ```

3. **Provide Codex with the Bootstrapping Instructions:**
   Once connected, you **must** instruct Codex to read the `BOOTSTRAP.md` file located in this repository. 
   This file provides Codex with the explicit instructions on how to structure the Multi-Agent Hierarchy and how to leverage `gemini-3.1-pro` and `gemini-3.6-flash` as subordinate agents.
   
   *Example Prompt for Codex:*
   > "I have just connected the gemini-delegator MCP server. Please read the `BOOTSTRAP.md` file in the gemini4codex repository and apply the agent synergy patterns to your global memory."

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
3. **Delegator Server** creates `.worktrees/wt-5f8a9b2c` and runs the `google.antigravity` SDK in-process inside it.
4. **Gemini** works in the background, modifying files. If it loops or gets stuck, the Supervisor auto-nudges it.
5. **Codex** periodically calls `get_agent_run_report("db-refactor")`. 
6. **Codex** reads the `git diff` returned by the report. "Looks good, the tests passed."
7. **Codex** calls `apply_agent_run("db-refactor")`.
8. **Delegator Server** squash merges the changes cleanly into the main branch.

## Security

This plugin aggressively restricts the Gemini subordinate worker:
- **Write Jailing**: If a worker is delegated to `./src/frontend`, any attempt to `write_to_file` in `./src/backend` or outside the workspace is instantly rejected by dynamically injected SDK hooks.
- **Git Sandboxing**: Workers are forbidden from running structural git commands (`git commit`, `git push`, `git merge`) or destructive operations (`rm -rf`).
- **Profile Segregation**: You can delegate a `scout` or `reviewer` profile, which disables all write tools completely.

## Architecture Map

The project is structured into three main layers:

```
gemini4codex/
├── pyproject.toml           # Python packaging and dependency config
├── BOOTSTRAP.md             # Essential instructions for Codex on how to use these agents
└── server/
    ├── gemini_delegator.py  # The FastMCP Server exposing endpoints to Codex
    ├── supervisor.py        # Async execution engine; parses stream-json & detects loops
    ├── worktree.py          # Git worktree isolation and squash-merge orchestrator
    ├── security.py          # Dynamic SDK hooks to jail the worker
    └── ledger.py            # SQLite WAL state manager for robust persistence
```

- **Layer 1: The Codex Interface** (`gemini_delegator.py`) handles all incoming MCP requests.
- **Layer 2: The Orchestrator** (`worktree.py` & `supervisor.py`) spins up the isolated environment and runs the process asynchronously via the Antigravity SDK.
- **Layer 3: The Jailed Subordinate** (`security.py`) restricts the worker's context natively so it cannot harm the host system or primary branch.
