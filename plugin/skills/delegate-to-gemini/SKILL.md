---
name: delegate-to-agent
description: Delegate tasks to isolated Antigravity/Gemini subagents for parallel execution, code review, or research.
---

# Delegate to Subagent

You can delegate complex, time-consuming, or isolated tasks to subordinate agents. 
Tasks run fully isolated in Git Worktrees, keeping your main branch safe.
Codex is the final authority and must verify all results before merging them back.

## Delegation Policy

1. **Check Existing Workers:** ALWAYS call `list_agent_runs` before delegating to see if an existing worker should resume this workstream.
2. **Reuse When Appropriate:** If a worker was doing related work, use `continue_agent_run` with its `worker_id` instead of spawning a new one.
3. **Build Bounded Contracts:** Use `delegate_to_agent` with clear constraints. Include the workspace path, success criteria, and a specific objective.
4. **Select Profile:**
   - `scout`: Read-only. Fast research and mapping.
   - `reviewer`: Read-only. Code review, security analysis, verification.
   - `worker`: Capable of writing code strictly within its isolated worktree.

## After Delegation

- Use `get_agent_run_report` to inspect completion status, JSON logs, and the **Git Diff**.
- Review the worktree diff provided in the report carefully. 
- If the work is incomplete or flawed, run `continue_agent_run` to send corrections.
- If the work is approved, use `apply_agent_run` to merge the worktree into the main branch.
- If the work is rejected and not worth saving, use `cleanup_agent_run` to delete the worktree.
