import asyncio

from server.agentapi import AntigravityLanguageServerAdapter
from server import agentapi as agentapi_module


def test_run_uses_agent_api_source_and_planner_model(tmp_path):
    calls = []
    cascade_id = "a1b2c3d4-e5f6-4789-abcd-0123456789ab"

    class FakeAdapter(AntigravityLanguageServerAdapter):
        async def _rpc(self, method, payload):
            calls.append((method, payload))
            if method == "GetAvailableModels":
                return {"models": {"gemini-3.6-flash-high": {"model": "MODEL_PLACEHOLDER_M71"}}}
            if method == "StartCascade":
                return {"cascadeId": cascade_id}
            if method == "SendUserCascadeMessage":
                return {}
            if method == "GetCascadeTrajectory":
                return {
                    "status": "CASCADE_RUN_STATUS_IDLE",
                    "trajectory": {
                        "steps": [
                            {
                                "plannerResponse": {
                                    "response": "BRIDGE_PROBE_OK",
                                }
                            }
                        ]
                    },
                }
            raise AssertionError(method)

    result = asyncio.run(
        FakeAdapter(address="127.0.0.1:1").run(
            "Reply exactly BRIDGE_PROBE_OK.",
            workspace=str(tmp_path),
            conversation_id=None,
            model="gemini-3.6-flash",
            profile="scout",
        )
    )

    assert result.conversation_id == cascade_id
    assert result.response == "BRIDGE_PROBE_OK"
    start = next(payload for method, payload in calls if method == "StartCascade")
    send = next(payload for method, payload in calls if method == "SendUserCascadeMessage")
    assert start["source"] == "CORTEX_TRAJECTORY_SOURCE_AGENT_API"
    assert start["requestedModel"] == "MODEL_PLACEHOLDER_M71"
    assert send["cascadeConfig"]["agentApiConfig"]["enabled"] is True
    assert send["cascadeConfig"]["plannerConfig"]["planModel"] == "MODEL_PLACEHOLDER_M71"
    assert "api_key" not in start
    assert "api_key" not in send


def test_discovery_skips_stale_config_and_uses_csrf_listener(monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_LS_ADDRESS", "127.0.0.1:52308")
    monkeypatch.delenv("ANTIGRAVITY_LS_PROTOCOL", raising=False)

    class _LsofResult:
        stdout = "Antigravi 123 dave 32u IPv4 TCP 127.0.0.1:53062 (LISTEN)\n"

    monkeypatch.setattr(agentapi_module.subprocess, "run", lambda *args, **kwargs: _LsofResult())

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b'<script>window.app = {"csrfToken":"token"}</script>'

    def _urlopen(url, timeout):
        if url.endswith(":53062/"):
            return _Response()
        raise agentapi_module.error.URLError("stale listener")

    monkeypatch.setattr(agentapi_module.request, "urlopen", _urlopen)

    assert (
        AntigravityLanguageServerAdapter._discover_address()
        == "http://127.0.0.1:53062"
    )
