import asyncio
import json
import logging
import uuid
import os
from datetime import datetime
from .ledger import LedgerDB

logger = logging.getLogger(__name__)

class GeminiSupervisor:
    def __init__(self, db: LedgerDB, logs_dir: str = None):
        self.db = db
        self.logs_dir = logs_dir or os.path.expanduser("~/.codex/gemini-delegator/logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        # Track active processes
        self._active_tasks = {}

    async def _run_gemini(self, worker_id: str, run_id: str, prompt: str, conversation_id: str = None, model: str = None, profile: str = None, workspace: str = None):
        import hashlib
        
        def _hash_tool(t_name, t_args):
            return hashlib.sha256((str(t_name) + json.dumps(t_args, sort_keys=True)).encode()).hexdigest()

        max_nudges = 2
        nudges_used = 0
        current_prompt = prompt
        
        while nudges_used <= max_nudges:
            log_path = os.path.join(self.logs_dir, f"{worker_id}_{run_id}_{nudges_used}.log")
            
            # Build the command
            cmd = ["gemini", "--output-format", "stream-json"]
            
            if conversation_id:
                cmd.extend(["--session-id", conversation_id])
            if model:
                cmd.extend(["-m", model])
            if workspace:
                cmd.extend(["--include-directories", workspace])
                
            cmd.extend(["-p", current_prompt])
            
            env = os.environ.copy()
            env["CODEX_SUPERVISED_WORKER"] = "1"
            if model:
                env["CODEX_SUPERVISED_MODEL"] = model
            if profile:
                env["CODEX_SUPERVISED_PROFILE"] = profile
            if workspace:
                env["CODEX_SUPERVISED_SCOPE"] = workspace
                
            logger.info(f"Starting gemini worker {worker_id} run {run_id} (nudge {nudges_used})")
            
            try:
                # Create process
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,  # Prevent deadlock by merging stderr into stdout
                    env=env,
                    cwd=workspace if workspace else None
                )
                
                # Update DB with PID
                self.db.create_run(run_id, worker_id, objective=current_prompt[:100], pid=process.pid, log_path=log_path)
                
                consecutive_failures = 0
                last_tool_hash = None
                consecutive_same_tools = 0
                loop_detected = False
                
                with open(log_path, "w") as log_file:
                    log_file.write(f"--- START RUN {run_id} (Worker {worker_id}) ---\n")
                    
                    # Read stdout line by line
                    async for line in process.stdout:
                        line_str = line.decode('utf-8').strip()
                        if not line_str:
                            continue
                        
                        log_file.write(line_str + "\n")
                        log_file.flush()
                        
                        try:
                            event = json.loads(line_str)
                            if isinstance(event, dict):
                                # Extract conversation_id if not known
                                if not conversation_id and event.get("type") == "session_start" and "session_id" in event:
                                    conversation_id = event["session_id"]
                                    self.db.update_worker(worker_id, conversation_id=conversation_id)
                                    
                                # Track current step
                                if "type" in event and event["type"] in ("tool_call", "model_response"):
                                    step = event.get("tool_name", event["type"])
                                    self.db.update_run(run_id, current_step=step)
                                
                                # Loop detection logic
                                if "type" in event and event["type"] == "tool_call":
                                    t_name = event.get("tool_name", "")
                                    t_args = event.get("tool_args", {})
                                    h = _hash_tool(t_name, t_args)
                                    if h == last_tool_hash:
                                        consecutive_same_tools += 1
                                    else:
                                        last_tool_hash = h
                                        consecutive_same_tools = 1
                                        
                                    if consecutive_same_tools >= 3:
                                        loop_detected = True
                                        
                                elif "type" in event and event["type"] == "tool_response":
                                    if not event.get("success", True):
                                        consecutive_failures += 1
                                    else:
                                        consecutive_failures = 0
                                        
                                    if consecutive_failures >= 4:
                                        loop_detected = True
                                        
                                if loop_detected:
                                    logger.warning(f"Loop detected for worker {worker_id}. Terminating process.")
                                    process.terminate()
                                    break
                                        
                        except json.JSONDecodeError:
                            pass
                    
                    # Wait for process to exit
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Process {process.pid} hung on termination, sending SIGKILL.")
                        process.kill()
                        await process.wait()
                    
                    exit_code = process.returncode
                    
                    if loop_detected:
                        if nudges_used < max_nudges:
                            nudges_used += 1
                            current_prompt = "SYSTEM NUDGE: Loop detected. You have attempted the same failing action repeatedly. Stop your current approach immediately and try a different strategy, or report failure to Codex."
                            logger.info(f"Applying nudge {nudges_used} to worker {worker_id}")
                            continue  # Restart the loop with new prompt
                        else:
                            status = "FAILED_LOOPING"
                            exit_code = 1
                    else:
                        status = "COMPLETED" if exit_code == 0 else "FAILED"
                    
                    logger.info(f"Worker {worker_id} run {run_id} finished with code {exit_code}")
                    
                    self.db.update_run(run_id, 
                                       status=status, 
                                       exit_code=exit_code, 
                                       end_time=datetime.utcnow().isoformat())
                    
                    self.db.update_worker(worker_id, state="IDLE" if exit_code == 0 else status)
                    break # Break out of the nudge loop if finished or out of nudges
                    
            except Exception as e:
                logger.error(f"Error running worker {worker_id}: {e}")
                self.db.update_run(run_id, 
                                   status="FAILED", 
                                   error=str(e), 
                                   end_time=datetime.utcnow().isoformat())
                self.db.update_worker(worker_id, state="FAILED")
                break
        
        # Finally block cleanup is handled after the while loop finishes
        if run_id in self._active_tasks:
            del self._active_tasks[run_id]

    async def delegate(self, worker_id: str, profile: str, workspace: str, model: str, effort: str, prompt: str):
        # Create worker in DB if new
        worker = self.db.get_worker(worker_id)
        if not worker:
            self.db.create_worker(worker_id, profile, workspace, model, effort, prompt[:200])
        else:
            self.db.update_worker(worker_id, state="RUNNING")
            
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        
        # Start background task
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
            
        run = self.db.get_run(run_id)
        if not run or not run.get("pid"):
            return False
            
        try:
            os.kill(run["pid"], 15) # SIGTERM
            self.db.update_run(run_id, status="CANCELLED", end_time=datetime.utcnow().isoformat())
            self.db.update_worker(worker_id, state="IDLE")
            return True
        except OSError:
            return False
