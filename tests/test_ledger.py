import os
import pytest
import sqlite3
from server.ledger import LedgerDB

@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_ledger.db"
    db = LedgerDB(str(db_path))
    yield db
    if os.path.exists(db_path):
        os.remove(db_path)

def test_create_worker(test_db):
    worker_id = test_db.create_worker("worker_1", "scout", "/test", "gemini-test", "low", "Test task")
    assert worker_id == "worker_1"
    
    worker = test_db.get_worker("worker_1")
    assert worker is not None
    assert worker["profile"] == "scout"
    assert worker["state"] == "INITIALIZING"

def test_create_run_updates_worker(test_db):
    test_db.create_worker("worker_1", "worker", "/test", "gemini", "high", "Task")
    test_db.create_run("run_1", "worker_1", "objective", 1234, "/path")
    
    run = test_db.get_run("run_1")
    assert run is not None
    assert run["status"] == "RUNNING"
    assert run["pid"] == 1234
    
    worker = test_db.get_worker("worker_1")
    assert worker["state"] == "RUNNING"
    assert worker["last_run_id"] == "run_1"

def test_update_run(test_db):
    test_db.create_worker("w1", "worker", "/t", "m", "e", "t")
    test_db.create_run("r1", "w1", "obj", 1, "/l")
    
    test_db.update_run("r1", status="COMPLETED", exit_code=0)
    
    run = test_db.get_run("r1")
    assert run["status"] == "COMPLETED"
    assert run["exit_code"] == 0

def test_stale_reconciliation(test_db):
    test_db.create_worker("w1", "worker", "/t", "m", "e", "t")
    # PID 999999 should not exist
    test_db.create_run("r1", "w1", "obj", 999999, "/l")
    
    test_db.reconcile_stale_runs()
    
    run = test_db.get_run("r1")
    assert run["status"] == "FAILED"
    
    worker = test_db.get_worker("w1")
    assert worker["state"] == "FAILED"
