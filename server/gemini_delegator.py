from mcp.server.fastmcp import FastMCP
import asyncio
import os
import json
import subprocess
from .ledger import LedgerDB
from .supervisor import GeminiSupervisor
from .worktree import WorktreeManager

# Initialize MCP server
mcp = FastMCP(
    "Codex Gemini Delegator V2",
    instructions="\"\"\"Gemini workers are subordinate to Codex. Check list_agent_runs before spawning work. "
    "Reuse existing worker IDs for the same workstream. Delegate bounded tasks with explicit scope and success criteria. "
    "Codex owns final decisions and must verify Gemini results. Never auto-commit, push, or merge delegated work.\"\"\""
)

# Initialize DB and Supervisor
db = LedgerDB()
db.reconcile_stale_runs()
supervisor = GeminiSupervisor(db)

@mcp.tool()
def list_agent_backends() -> str:
    """List available agent backends and check their health."""
    checks = []
    
    # Check Antigravity SDK
    try:
        import google.antigravity
        checks.append("✅ google-antigravity SDK found")
    except ImportError:
        checks.append("❌ google-antigravity SDK missing")
        
    # Check DB
    try:
        db.get_all_workers()
        checks.append(f"✅ SQLite DB accessible ({db.db_path})")
    except Exception as e:
        checks.append(f"❌ SQLite DB error: {e}")
        
    return "\n".join(checks)

@mcp.tool()
def list_agent_runs() -> str:
    """List all agent runs, their states, and recent activity. Use this before creating new workers."""
    workers = db.get_all_workers()
    if not workers:
        return "No agent runs found."
        
    running = []
    idle = []
    failed = []
    
    for w in workers:
        state = w.get("state", "UNKNOWN")
        wt = w.get("worktree_uuid", "none")
        info = f"- {w['worker_id']} | {w.get('profile', 'worker')} | WT:{wt} | {w.get('task_summary', 'No summary')} | {w.get('last_seen_at')}"
        if state == "RUNNING":
            running.append(info)
        elif state == "FAILED" or state == "FAILED_LOOPING":
            failed.append(info)
        else:
            idle.append(info)
            
    res = []
    if running:
        res.append("RUNNING WORKERS:")
        res.extend(running)
    if idle:
        res.append("\nIDLE / RESUMABLE WORKERS:")
        res.extend(idle)
    if failed:
        res.append("\nFAILED WORKERS:")
        res.extend(failed)
        
    return "\n".join(res)

@mcp.tool()
async def delegate_to_agent(
    worker_id: str,
    objective: str,
    context: str,
    workspace_path: str,
    profile: str = "worker",
    model: str = None,
    effort: str = "high"
) -> str:
    """Delegate a new task to a Gemini worker. Creates a new Git worktree for isolated execution."""
    
    # Enforce detailed objective
    if len(objective) < 20:
        return "Error: Objective is too short. Provide a detailed task contract with scope and success criteria."
        
    # 1. Create Worktree if it's a git repo
    wt_uuid = None
    target_workspace = workspace_path
    
    if WorktreeManager.is_git_repo(workspace_path):
        res = WorktreeManager.create_worktree(workspace_path)
        if res:
            wt_uuid, target_workspace = res
            # Save worktree metadata to database before supervisor.delegate()
            worker = db.get_worker(worker_id)
            if not worker:
                db.create_worker(worker_id, profile, target_workspace, model, effort, objective[:200])
            db.update_worker(worker_id, worktree_uuid=wt_uuid, original_workspace=workspace_path)
        else:
            return json.dumps({"status": "FAILED", "message": "Error: Failed to create isolated worktree for this task."})
            
    prompt = f"Objective: {objective}\nContext: {context}"
    
    # 2. Delegate to supervisor
    run_id = await supervisor.delegate(
        worker_id=worker_id,
        profile=profile,
        workspace=target_workspace,
        model=model,
        effort=effort,
        prompt=prompt
    )
    
    return json.dumps({
        "status": "STARTED",
        "worker_id": worker_id,
        "run_id": run_id,
        "worktree": wt_uuid,
        "message": f"Worker {worker_id} started successfully in isolated worktree {wt_uuid}." if wt_uuid else f"Worker {worker_id} started."
    })

@mcp.tool()
async def continue_agent_run(
    worker_id: str,
    instruction: str
) -> str:
    """Send follow-up instructions to an existing Gemini worker to continue its workstream."""
    worker = db.get_worker(worker_id)
    if not worker:
        return f"Error: Worker {worker_id} not found."
        
    if worker.get("state") == "RUNNING":
        return f"Error: Worker {worker_id} is currently busy."
        
    run_id = await supervisor.delegate(
        worker_id=worker_id,
        profile=worker.get("profile"),
        workspace=worker.get("workspace"),
        model=worker.get("model"),
        effort=worker.get("effort"),
        prompt=instruction
    )
    
    return json.dumps({
        "status": "STARTED",
        "worker_id": worker_id,
        "run_id": run_id,
        "message": f"Worker {worker_id} resumed with new instruction."
    })

@mcp.tool()
def get_agent_run_report(worker_id: str) -> str:
    """Get the full results, recent events, and the Git diff of an agent run."""
    worker = db.get_worker(worker_id)
    if not worker:
        return f"Error: Worker {worker_id} not found."
        
    runs = db.get_runs_for_worker(worker_id)
    
    result = {
        "worker": worker,
        "runs": runs[:5] # Return last 5 runs
    }
    
    wt_uuid = worker.get("worktree_uuid")
    if wt_uuid:
        diff = WorktreeManager.extract_diff(worker.get("original_workspace"), wt_uuid)
        if diff:
            result["worktree_diff"] = diff
        else:
            result["worktree_diff"] = "No changes or failed to extract diff."
            
    return json.dumps(result, indent=2)

@mcp.tool()
async def apply_agent_run(worker_id: str) -> str:
    """Merge the changes from the agent's worktree back into the main branch."""
    worker = db.get_worker(worker_id)
    if not worker:
        return f"Error: Worker {worker_id} not found."
        
    wt_uuid = worker.get("worktree_uuid")
    if not wt_uuid:
        return f"Error: Worker {worker_id} does not have an active worktree."
        
    orig_workspace = worker.get("original_workspace")
    success = WorktreeManager.apply_run(orig_workspace, wt_uuid)
    
    if success:
        WorktreeManager.cleanup_worktree(orig_workspace, wt_uuid)
        db.update_worker(worker_id, worktree_uuid=None, original_workspace=None)
        return f"Successfully merged worktree {wt_uuid} into main branch and cleaned it up."
    else:
        return f"Failed to merge worktree {wt_uuid}. There may be conflicts."

@mcp.tool()
async def cleanup_agent_run(worker_id: str) -> str:
    """Cancel a running agent and delete its temporary worktree."""
    worker = db.get_worker(worker_id)
    if not worker:
        return f"Error: Worker {worker_id} not found."
        
    if worker.get("state") == "RUNNING":
        await supervisor.cancel(worker_id)
        
    wt_uuid = worker.get("worktree_uuid")
    if wt_uuid:
        orig_workspace = worker.get("original_workspace")
        WorktreeManager.cleanup_worktree(orig_workspace, wt_uuid)
        db.update_worker(worker_id, worktree_uuid=None, original_workspace=None)
        return f"Worker {worker_id} cancelled and worktree {wt_uuid} cleaned up."
        
    return f"Worker {worker_id} cancelled."

if __name__ == "__main__":
    mcp.run()
