import asyncio

from server import supervisor as supervisor_module
from server.ledger import LedgerDB
from server.supervisor import GeminiSupervisor, WorkerRunOutput


def test_run_persists_and_completes_with_current_post_tool_hook(tmp_path, monkeypatch):
    """A current Antigravity hook API must not prevent a worker run from starting."""

    class FakeResponse:
        async def structured_output(self):
            return WorkerRunOutput(
                status="COMPLETED",
                summary="Inspection complete.",
                files_modified=[],
                blockers=[],
            )

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def chat(self, prompt):
            return FakeResponse()

    db = LedgerDB(str(tmp_path / "ledger.db"))
    db.create_worker("worker-1", "scout", str(tmp_path), None, "low", "inspect")
    monkeypatch.setattr(supervisor_module, "Agent", FakeAgent)
    supervisor = GeminiSupervisor(db, logs_dir=str(tmp_path / "logs"))

    asyncio.run(
        supervisor._run_gemini(
            worker_id="worker-1",
            run_id="run-1",
            prompt="Inspect the workspace.",
            profile="scout",
            workspace=str(tmp_path),
        )
    )

    assert db.get_run("run-1")["status"] == "COMPLETED"
    assert db.get_worker("worker-1")["state"] == "IDLE"
