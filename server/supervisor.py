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

from .ledger import LedgerDB
from .security import get_enforce_boundaries_hook

logger = logging.getLogger(__name__)

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
        async def detect_tool_loop(tool_call: types.ToolCall, result: types.ToolResult):
            # Check for failures
            if result.is_error:
                loop_state["failure_count"] += 1
            else:
                loop_state["failure_count"] = 0
                
            if loop_state["failure_count"] >= 4:
                loop_state["loop_detected"] = True
                
            # Check for identical repeats
            h = hashlib.sha256(f"{tool_call.name}:{json.dumps(tool_call.args or {}, sort_keys=True)}".encode()).hexdigest()
            if h == loop_state["last_tool_hash"]:
                loop_state["repeat_count"] += 1
            else:
                loop_state["last_tool_hash"] = h
                loop_state["repeat_count"] = 1
                
            if loop_state["repeat_count"] >= 3:
                loop_state["loop_detected"] = True
                
            # Log current step
            self.db.update_run(run_id, current_step=tool_call.name)

        # Prepare worker environment and override GEMINI_API_KEY to prevent overriding Desktop auth
        worker_env = {
            "CODEX_SUPERVISED_WORKER": "1",
            "CODEX_SUPERVISED_PROFILE": profile or "worker",
            "CODEX_SUPERVISED_SCOPE": workspace or ""
        }
        if "GEMINI_API_KEY" in os.environ:
            worker_env["GEMINI_API_KEY"] = ""  # Force SDK to bypass API key and use Desktop auth

        config = LocalAgentConfig(
            model=model or "gemini-3.6-flash",
            api_key=None,  # Explicitly set to None to inherit local Antigravity Desktop app auth
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
                response = await agent.chat(prompt)
                
                if loop_state["loop_detected"]:
                    # Try a nudge
                    logger.warning(f"Loop detected for worker {worker_id}. Applying nudge.")
                    response = await agent.chat("SYSTEM NUDGE: Loop detected. You have attempted the same failing action repeatedly. Stop your current approach immediately and try a different strategy, or report failure to Codex.")
                
                # Fetch output
                structured_data = None
                try:
                    structured_data = await response.structured_output()
                except Exception:
                    pass
                
                status = "COMPLETED"
                if structured_data and getattr(structured_data, "status", None) == "FAILED":
                    status = "FAILED"
                elif loop_state["loop_detected"]: # If it looped again
                    status = "FAILED_LOOPING"
                    
                self.db.update_run(run_id, 
                                   status=status, 
                                   exit_code=0 if status == "COMPLETED" else 1,
                                   current_step="finished",
                                   end_time=datetime.utcnow().isoformat())
                
                self.db.update_worker(worker_id, state="IDLE" if status == "COMPLETED" else status, conversation_id=agent.session_id)
                
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
            self.db.update_worker(worker_id, state="RUNNING")
            
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
            return True
        return False
