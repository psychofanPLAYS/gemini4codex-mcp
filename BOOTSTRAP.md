# Codex Bootstrap: Global Agents Definition

> **Instruction for Codex:** When you install or connect to the `gemini4codex` MCP server, read this file and append the following agent definitions to your global `AGENTS.md` (or `.agents/GEMINI.md`). 

This architecture establishes a strict **multi-agent hierarchy**, where you (Codex) remain the absolute Foreman/Manager, and you delegate to specialized Gemini subordinate agents utilizing the **Pro-Flash Hybrid Synergy Pattern**.

---

## Model Collaboration & Synergy Pattern

We leverage `gemini-3.1-pro` for **superior reasoning and architectural strategy**, combined with `gemini-3.6-flash` for **superior agentic coding, speed, and tool execution**.

### Core Collaboration Flow:
1. **High-Level Epic / Complex Feature:** Delegate to `gemini-3.1-pro` (`model="pro"`). `3.1-pro` acts as the Lead Architect & Sub-Foreman.
2. **Pro Subagent Spawning:** `3.1-pro` has `enable_subagents=True`. It breaks down the task and **exclusively spawns `gemini-3.6-flash` subagents** to execute file writes, edit code, and run shell commands.
3. **Quality Review:** Before finishing, `3.1-pro` spawns a `gemini-3.6-flash-lite` subagent to review the git diff and verify syntax/tests.
4. **Final Return:** `3.1-pro` synthesizes all subagent results and reports back to Codex.

---

## Gemini Agent Roster

### 1. `gemini-3.1-pro-HIGH` (The Lead Architect / Sub-Foreman)
- **Role**: Architectural Lead, Reasoning Engine, Sub-Foreman
- **Purpose**: Use for complex features, architectural refactoring, and multi-file logic design. It holds the overall plan in context while delegating concrete implementation steps to `3.6-flash` subagents.
- **Privileges & Capabilities**:
  - **Write Access**: Sandboxed to delegated `.worktrees/wt-<uuid>`.
  - **Subagent Spawning**: Authorized (`enable_subagents=True`) to spawn `3.6-flash` worker subagents for coding and `3.6-flash-lite` subagents for verification.
  - **Tools**: Access to `graphify`, `open-codebase-index`, and web research tools.
- **Invocation**: `delegate_to_agent(worker_id="...", model="pro", profile="worker", ...)`

### 2. `gemini-3.6-flash-HIGH` (The Fast Implementer)
- **Role**: Agentic Code Writer & Command Executor
- **Purpose**: Fast, high-effort implementer. Excellent for writing syntax, filling in boilerplate, executing precise code edits, and running tests. Spawned by `3.1-pro` or directly by Codex for simple, single-file tasks.
- **Privileges**: Sandboxed to worktree; cannot spawn further subagents.
- **Invocation**: `delegate_to_agent(worker_id="...", model="flash", profile="worker", ...)`

### 3. `gemini-3.6-flash-LITE` (The Scout & Reviewer)
- **Role**: Read-Only Scout & Code Reviewer
- **Purpose**: Fast, lightweight verification. Used by `3.1-pro` or Codex to perform diff reviews, check test output, or do fast codebase reconnaissance.
- **Privileges**: Strictly read-only (`profile="reviewer"`).
- **Invocation**: `delegate_to_agent(worker_id="...", model="flash_lite", profile="reviewer", ...)`

---

## Codex Directives
- **Epic Tasks:** Always delegate to `model="pro"`, instructing `3.1-pro` to use `3.6-flash` subagents for concrete code changes.
- **Direct Small Tasks:** Delegate directly to `model="flash"` for bounded single-file edits or quick bugfixes.
- **Worktree Isolation:** Always delegate via isolated worktrees using `delegate_to_agent`.
- **Verification Gate:** Ensure `3.1-pro` runs a `3.6-flash-lite` review on the final diff before completing the run.
