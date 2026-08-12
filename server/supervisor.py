import asyncio
import json
import logging
import uuid
import os
from datetime import datetime
from pydantic import BaseModel, Field

from .agentapi import AntigravityLanguageServerAdapter
from .ledger import LedgerDB

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

        logger.info(f"Starting Antigravity language-server worker {worker_id} run {run_id}")
        self.db.create_run(run_id, worker_id, objective=prompt[:100], pid=0, log_path=log_path)

        agent = AntigravityLanguageServerAdapter()
        self._active_agents[run_id] = agent
        
        try:
            result = await agent.run(
                prompt=prompt,
                workspace=workspace or os.getcwd(),
                conversation_id=conversation_id,
                model=model,
                profile=profile,
            )
            structured_data = self._parse_worker_output(result.response)
            status = "FAILED" if structured_data.status == "FAILED" else "COMPLETED"

            self.db.update_run(
                run_id,
                status=status,
                exit_code=0 if status == "COMPLETED" else 1,
                current_step="finished",
                result_summary=structured_data.summary,
                end_time=datetime.utcnow().isoformat(),
            )
            self.db.update_worker(
                worker_id,
                state="IDLE" if status == "COMPLETED" else status,
                conversation_id=result.conversation_id,
            )
                
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

    @staticmethod
    def _parse_worker_output(response: str) -> WorkerRunOutput:
        candidate = response.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`").strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
        try:
            return WorkerRunOutput.model_validate(json.loads(candidate))
        except (ValueError, TypeError, json.JSONDecodeError):
            return WorkerRunOutput(
                status="COMPLETED",
                summary=response,
                files_modified=[],
                blockers=[],
            )

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
