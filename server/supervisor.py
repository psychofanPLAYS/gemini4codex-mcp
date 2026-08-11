import asyncio
import json
import logging
import uuid
import os
import hashlib
from datetime import datetime
from pydantic import BaseModel, Field

from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks import hooks
import google.antigravity.models

from .ledger import LedgerDB
from .security import get_enforce_boundaries_hook

logger = logging.getLogger(__name__)

# The local Antigravity harness rejects an empty transport key before it can
# load the Desktop app's OAuth credentials. This sentinel is not a credential;
# Antigravity resolves the actual account from app_data_dir.
ANTIGRAVITY_LOCAL_TRANSPORT_KEY = "antigravity-local"

# Monkey-patch SDK to bypass the artificial api_key requirement.
# This allows the MCP server to piggyback off the local Antigravity Desktop app's Pro Subscription credentials.
google.antigravity.models.GeminiAPIEndpoint.validate_endpoint = lambda self: None

class WorkerRunOutput(BaseModel):
    status: str = Field(description="'COMPLETED', 'FAILED', or 'BLOCKED'")
    summary: str = Field(description="Summary of what was achieved")
    files_modified: list[str] = Field(description="List of files that were modified")
    blockers: list[str] = Field(description="List of blockers or errors encountered")

class GeminiSupervisor:
    def __init__(self, db: LedgerDB, logs_dir: str = None):
        self.db = db
        self.logs_dir = logs_dir or os.path.expanduser("~/.codex/gemini-delegator/logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        # Track active tasks instead of PIDs
        self._active_tasks = {}
        self._active_agents = {} # Maps run_id to Agent instance for cancellation

    async def _run_gemini(self, worker_id: str, run_id: str, prompt: str, conversation_id: str = None, model: str = None, profile: str = None, workspace: str = None):
        log_path = os.path.join(self.logs_dir, f"{worker_id}_{run_id}.log")
        
        # Determine capabilities
        is_pro = "pro" in (model or "").lower()
        
        # State for loop detection
        loop_state = {
            "last_tool_hash": None,
            "repeat_count": 0,
            "failure_count": 0,
            "loop_detected": False
        }
        
        @hooks.post_tool_call
        async def detect_tool_loop(result: types.ToolResult):
            # Check for failures
            if result.error is not None or result.exception is not None:
                loop_state["failure_count"] += 1
            else:
                loop_state["failure_count"] = 0
                
            if loop_state["failure_count"] >= 4:
                loop_state["loop_detected"] = True
                
            # Check for identical repeats
            h = hashlib.sha256(
                f"{result.name}:{json.dumps(result.result, sort_keys=True, default=str)}".encode()
            ).hexdigest()
            if h == loop_state["last_tool_hash"]:
                loop_state["repeat_count"] += 1
            else:
                loop_state["last_tool_hash"] = h
                loop_state["repeat_count"] = 1
                
            if loop_state["repeat_count"] >= 3:
                loop_state["loop_detected"] = True
                
            # Log current step
            self.db.update_run(run_id, current_step=result.name)
            
            if loop_state["loop_detected"]:
                raise RuntimeError("SupervisorLoopDetected")

        worker_env = {
            "CODEX_SUPERVISED_WORKER": "1",
            "CODEX_SUPERVISED_PROFILE": profile or "worker",
            "CODEX_SUPERVISED_SCOPE": workspace or ""
        }

        # Load global GEMINI.md rules if they exist
        global_rules = ""
        mcp_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        gemini_md_path = os.path.join(mcp_root, "GEMINI.md")
        if os.path.exists(gemini_md_path):
            try:
                with open(gemini_md_path, "r") as f:
                    global_rules = f.read()
            except Exception as e:
                logger.error(f"Failed to read GEMINI.md: {e}")

        config = LocalAgentConfig(
            model=model or "gemini-3.6-flash",
            api_key=ANTIGRAVITY_LOCAL_TRANSPORT_KEY,
            instructions=global_rules if global_rules else None,
            capabilities=types.CapabilitiesConfig(
                enable_subagents=is_pro
            ),
            session_id=conversation_id,
            hooks=[get_enforce_boundaries_hook(profile or "worker", workspace or ""), detect_tool_loop],
            app_data_dir=os.path.expanduser("~/.gemini/antigravity"),  # Point to desktop app context where Pro Subscription credentials reside
            env=worker_env,
            response_schema=WorkerRunOutput
        )

        logger.info(f"Starting native gemini worker {worker_id} run {run_id}")
        self.db.create_run(run_id, worker_id, objective=prompt[:100], pid=0, log_path=log_path)

        agent = Agent(config)
        self._active_agents[run_id] = agent
        
        try:
            async with agent:
                try:
                    response = await agent.chat(prompt)
                except RuntimeError as e:
                    if str(e) == "SupervisorLoopDetected":
                        pass
                    else:
                        raise e
                
                if loop_state["loop_detected"]:
                    # Try a nudge
                    logger.warning(f"Loop detected for worker {worker_id}. Applying nudge.")
                    loop_state["loop_detected"] = False
                    loop_state["repeat_count"] = 0
                    loop_state["failure_count"] = 0
                    loop_state["last_tool_hash"] = None
                    response = await agent.chat("SYSTEM NUDGE: Loop detected. You have attempted the same failing action repeatedly. Stop your current approach immediately and try a different strategy, or report failure to Codex.")
                
                # Fetch output
                structured_data = None
                try:
                    structured_data = await response.structured_output()
                except Exception as e:
                    logger.error(f"Failed to parse structured output for {worker_id}: {e}")
                
                status = "COMPLETED"
                if structured_data and getattr(structured_data, "status", None) == "FAILED":
                    status = "FAILED"
                elif loop_state["loop_detected"]: # If it looped again
                    status = "FAILED_LOOPING"
                    
                # Fix Erasure Loop: auto-commit successful runs to their isolated worktree branch
                if status == "COMPLETED" and profile not in ["scout", "reviewer"] and workspace:
                    try:
                        import subprocess
                        res = subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True)
                        if res.stdout.strip():
                            subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
                            subprocess.run(["git", "-c", "user.name=Gemini Worker", "-c", "user.email=worker@codex.ai", "commit", "-m", f"Auto-commit worker output ({run_id})"], cwd=workspace, check=True)
                    except Exception as git_e:
                        logger.error(f"Failed to auto-commit worker {worker_id} changes: {git_e}")
                        
                self.db.update_run(run_id, 
                                   status=status, 
                                   exit_code=0 if status == "COMPLETED" else 1,
                                   current_step="finished",
                                   end_time=datetime.utcnow().isoformat())
                
                self.db.update_worker(worker_id, state="IDLE" if status == "COMPLETED" else status, conversation_id=conversation_id)
                
        except asyncio.CancelledError:
            logger.info(f"Worker {worker_id} run {run_id} was cancelled.")
            self.db.update_run(run_id, status="CANCELLED", end_time=datetime.utcnow().isoformat())
            self.db.update_worker(worker_id, state="IDLE")
        except Exception as e:
            logger.error(f"Error running worker {worker_id}: {e}")
            self.db.update_run(run_id, 
                               status="FAILED", 
                               error=str(e), 
                               end_time=datetime.utcnow().isoformat())
            self.db.update_worker(worker_id, state="FAILED")
        finally:
            if run_id in self._active_tasks:
                del self._active_tasks[run_id]
            if run_id in self._active_agents:
                del self._active_agents[run_id]

    async def delegate(self, worker_id: str, profile: str, workspace: str, model: str, effort: str, prompt: str):
        worker = self.db.get_worker(worker_id)
        if not worker:
            self.db.create_worker(worker_id, profile, workspace, model, effort, prompt[:200])
        else:
            self.db.update_worker(worker_id, state="INITIALIZING", profile=profile, workspace=workspace, model=model, effort=effort)
            
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        
        task = asyncio.create_task(self._run_gemini(
            worker_id=worker_id,
            run_id=run_id,
            prompt=prompt,
            conversation_id=worker.get("conversation_id") if worker else None,
            model=model or (worker.get("model") if worker else None),
            profile=profile or (worker.get("profile") if worker else None),
            workspace=workspace or (worker.get("workspace") if worker else None)
        ))
        
        self._active_tasks[run_id] = task
        return run_id

    async def cancel(self, worker_id: str):
        worker = self.db.get_worker(worker_id)
        if not worker or worker.get("state") != "RUNNING":
            return False
            
        run_id = worker.get("last_run_id")
        if not run_id:
            return False
            
        task = self._active_tasks.get(run_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True
        return False
