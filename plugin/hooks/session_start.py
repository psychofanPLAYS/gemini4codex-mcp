#!/usr/bin/env python3
import sqlite3
import os
import sys

def main():
    db_path = os.environ.get("GEMINI_DELEGATOR_DB", os.path.expanduser("~/.codex/gemini-delegator/ledger.db"))
    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT worker_id, state, task_summary FROM workers ORDER BY last_seen_at DESC LIMIT 10")
        workers = cur.fetchall()
        
        running = [w for w in workers if w['state'] == 'RUNNING']
        idle = [w for w in workers if w['state'] != 'RUNNING']
        
        if not workers:
            return
            
        print("<system_message>")
        print(f"Gemini delegation state: {len(running)} running worker(s) and {len(idle)} resumable worker(s).")
        
        for w in running:
            print(f"RUNNING {w['worker_id']}: {w['task_summary']}")
            
        for w in idle[:3]:
            print(f"IDLE {w['worker_id']}: {w['task_summary']}")
            
        print("Use gemini_overview before spawning overlapping Gemini work. Continue existing worker IDs when the workstream matches.")
        print("</system_message>")
        
    except Exception as e:
        print(f"<system_message>Error reading Gemini ledger: {e}</system_message>")

if __name__ == "__main__":
    main()
