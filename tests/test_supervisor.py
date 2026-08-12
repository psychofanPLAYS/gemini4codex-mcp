import asyncio

from server import supervisor as supervisor_module
from server.agentapi import AgentAPIResult
from server.ledger import LedgerDB
from server.supervisor import GeminiSupervisor


def test_run_persists_and_completes_with_current_post_tool_hook(tmp_path, monkeypatch):
    """The supervisor uses the language-server bridge instead of localharness."""

    captured = {}

    class FakeAdapter:
        def __init__(self):
            captured["adapter"] = self

        async def run(self, prompt, workspace, conversation_id, model, profile):
            captured.update(
                prompt=prompt,
                workspace=workspace,
                conversation_id=conversation_id,
                model=model,
                profile=profile,
            )
            return AgentAPIResult(
                conversation_id="a1b2c3d4-e5f6-4789-abcd-0123456789ab",
                response='{"status":"COMPLETED","summary":"Inspection complete.","files_modified":[],"blockers":[]}',
            )

    db = LedgerDB(str(tmp_path / "ledger.db"))
    db.create_worker("worker-1", "scout", str(tmp_path), None, "low", "inspect")
    monkeypatch.setattr(supervisor_module, "AntigravityLanguageServerAdapter", FakeAdapter)
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
    assert captured["conversation_id"] is None
    assert captured["workspace"] == str(tmp_path)
    assert "api_key" not in vars(captured["adapter"])
