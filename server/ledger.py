import sqlite3
import json
import os
import contextlib
from typing import Dict, Any, List, Optional
from datetime import datetime

class LedgerDB:
    def __init__(self, db_path: str = None):
        if not db_path:
            db_path = os.environ.get("GEMINI_DELEGATOR_DB", os.path.expanduser("~/.codex/gemini-delegator/ledger.db"))
            
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextlib.contextmanager
    def _transaction(self):
        conn = self._get_conn()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    profile TEXT,
                    workspace TEXT,
                    model TEXT,
                    effort TEXT,
                    created_at TIMESTAMP,
                    last_seen_at TIMESTAMP,
                    state TEXT,
                    task_summary TEXT,
                    last_run_id TEXT,
                    worktree_uuid TEXT,
                    original_workspace TEXT
                );
            """)
            
            cur = conn.execute("PRAGMA table_info(workers)")
            columns = [row['name'] for row in cur.fetchall()]
            if 'worktree_uuid' not in columns:
                conn.execute("ALTER TABLE workers ADD COLUMN worktree_uuid TEXT")
            if 'original_workspace' not in columns:
                conn.execute("ALTER TABLE workers ADD COLUMN original_workspace TEXT")

        with self._transaction() as conn:
            conn.executescript("""

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    worker_id TEXT,
                    objective TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    status TEXT,
                    pid INTEGER,
                    exit_code INTEGER,
                    current_step TEXT,
                    result_summary TEXT,
                    error TEXT,
                    log_path TEXT,
                    FOREIGN KEY(worker_id) REFERENCES workers(worker_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_runs_worker_id ON runs(worker_id);
            """)

    def create_worker(self, worker_id: str, profile: str, workspace: str, model: str, effort: str, task_summary: str) -> str:
        now = datetime.utcnow().isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO workers (worker_id, profile, workspace, model, effort, created_at, last_seen_at, state, task_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (worker_id, profile, workspace, model, effort, now, now, "INITIALIZING", task_summary))
        return worker_id

    def update_worker(self, worker_id: str, **kwargs):
        if not kwargs:
            return
        
        valid_columns = {"worker_id", "conversation_id", "profile", "workspace", "model", "effort", "created_at", "last_seen_at", "state", "task_summary", "last_run_id", "worktree_uuid", "original_workspace"}
        
        now = datetime.utcnow().isoformat()
        kwargs['last_seen_at'] = now
        
        set_clause = []
        values = []
        for k, v in kwargs.items():
            if k in valid_columns:
                set_clause.append(f"{k} = ?")
                values.append(v)
                
        if not set_clause:
            return
            
        values.append(worker_id)
        
        with self._transaction() as conn:
            conn.execute(f"UPDATE workers SET {', '.join(set_clause)} WHERE worker_id = ?", values)

    def get_worker(self, worker_id: str) -> Optional[Dict]:
        with self._transaction() as conn:
            cur = conn.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_workers(self) -> List[Dict]:
        with self._transaction() as conn:
            cur = conn.execute("SELECT * FROM workers ORDER BY last_seen_at DESC")
            return [dict(row) for row in cur.fetchall()]

    def create_run(self, run_id: str, worker_id: str, objective: str, pid: int, log_path: str):
        now = datetime.utcnow().isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO runs (run_id, worker_id, objective, start_time, status, pid, log_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (run_id, worker_id, objective, now, "RUNNING", pid, log_path))
            
            # Update worker state
            conn.execute("""
                UPDATE workers SET state = 'RUNNING', last_run_id = ?, last_seen_at = ? WHERE worker_id = ?
            """, (run_id, now, worker_id))

    def update_run(self, run_id: str, **kwargs):
        if not kwargs:
            return
            
        valid_columns = {"run_id", "worker_id", "objective", "start_time", "end_time", "status", "pid", "exit_code", "current_step", "result_summary", "error", "log_path"}
        
        set_clause = []
        values = []
        for k, v in kwargs.items():
            if k in valid_columns:
                set_clause.append(f"{k} = ?")
                values.append(v)
                
        if not set_clause:
            return
            
        values.append(run_id)
        
        with self._transaction() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(set_clause)} WHERE run_id = ?", values)

    def get_run(self, run_id: str) -> Optional[Dict]:
        with self._transaction() as conn:
            cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            return dict(row) if row else None
            
    def get_runs_for_worker(self, worker_id: str) -> List[Dict]:
        with self._transaction() as conn:
            cur = conn.execute("SELECT * FROM runs WHERE worker_id = ? ORDER BY start_time DESC", (worker_id,))
            return [dict(row) for row in cur.fetchall()]

    def reconcile_stale_runs(self):
        """Find runs and workers marked as RUNNING from previous crashes and mark them FAILED."""
        with self._transaction() as conn:
            now = datetime.utcnow().isoformat()
            
            # Find all running runs
            cur = conn.execute("SELECT run_id, worker_id FROM runs WHERE status = 'RUNNING'")
            runs = cur.fetchall()
            for row in runs:
                conn.execute("UPDATE runs SET status = 'FAILED', error = 'Process terminated unexpectedly', end_time = ? WHERE run_id = ?", (now, row['run_id']))
                conn.execute("UPDATE workers SET state = 'FAILED', last_seen_at = ? WHERE worker_id = ?", (now, row['worker_id']))
                
            # Fail any orphaned workers that are stuck
            conn.execute("UPDATE workers SET state = 'FAILED', last_seen_at = ? WHERE state IN ('RUNNING', 'INITIALIZING')", (now,))
