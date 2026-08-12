"""Small JSON/Connect client for the Antigravity language-server bridge."""

import asyncio
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request


class LanguageServerError(RuntimeError):
    """Raised when the Antigravity language-server bridge rejects a request."""


@dataclass(frozen=True)
class AgentAPIResult:
    conversation_id: str
    response: str


class AntigravityLanguageServerAdapter:
    """Run a worker through the already-running Antigravity language server.

    This intentionally does not construct ``LocalAgentConfig``. That SDK path
    launches a separate localharness process and has a different credential
    boundary from the Antigravity Desktop language server.
    """

    _default_model = "gemini-3.6-flash-high"
    _default_poll_interval = 0.5
    _default_timeout = 600.0

    def __init__(self, address: str | None = None):
        self.address = address or self._discover_address()
        if not self.address:
            raise LanguageServerError(
                "could not discover the Antigravity language server; "
                "set ANTIGRAVITY_LS_ADDRESS to override discovery"
            )
        self.poll_interval = float(
            os.environ.get("ANTIGRAVITY_LS_POLL_INTERVAL", self._default_poll_interval)
        )
        self.timeout = float(
            os.environ.get("ANTIGRAVITY_LS_TIMEOUT", self._default_timeout)
        )

    @classmethod
    def _discover_address(cls) -> str | None:
        """Find the live Antigravity HTTP listener when its port has moved."""
        configured = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
        candidates = [configured] if configured else []
        for process_name in ("Antigravity", "language_server"):
            try:
                result = subprocess.run(
                    ["lsof", "-nP", "-a", "-c", process_name, "-iTCP", "-sTCP:LISTEN"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=3,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            for line in result.stdout.splitlines():
                match = re.search(r"127\.0\.0\.1:(\d+)", line)
                if match:
                    candidate = f"127.0.0.1:{match.group(1)}"
                    if candidate not in candidates:
                        candidates.append(candidate)

        configured_protocol = os.environ.get("ANTIGRAVITY_LS_PROTOCOL", "").strip()
        protocols = [configured_protocol] if configured_protocol else ["http", "https"]
        for candidate in candidates:
            if "://" in candidate:
                urls = [candidate.rstrip("/")]
            else:
                urls = [f"{protocol}://{candidate}" for protocol in protocols]
            for base_url in urls:
                try:
                    with request.urlopen(f"{base_url}/", timeout=2) as response:
                        html = response.read(64 * 1024).decode("utf-8", errors="replace")
                except (error.URLError, OSError):
                    continue
                if re.search(r'"csrfToken"\s*:\s*"[^"]+"', html):
                    return base_url
        return None

    @property
    def _base_url(self) -> str:
        if "://" in self.address:
            return self.address.rstrip("/")
        protocol = os.environ.get("ANTIGRAVITY_LS_PROTOCOL", "http")
        return f"{protocol}://{self.address}"

    def _csrf_token(self) -> str:
        try:
            with request.urlopen(f"{self._base_url}/", timeout=10) as response:
                html = response.read().decode("utf-8")
        except (error.URLError, OSError) as exc:
            raise LanguageServerError("could not reach the Antigravity language server") from exc

        match = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', html)
        if not match:
            raise LanguageServerError("Antigravity language server did not expose a CSRF token")
        return match.group(1)

    def _rpc_sync(self, method: str, payload: dict) -> dict:
        token = self._csrf_token()
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": token,
        }
        try:
            req = request.Request(
                f"{self._base_url}/exa.language_server_pb.LanguageServerService/{method}",
                data=body,
                headers=headers,
                method="POST",
            )
            with request.urlopen(req, timeout=30) as response:
                response_body = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LanguageServerError(f"{method} failed ({exc.code}): {detail}") from exc
        except (error.URLError, OSError) as exc:
            raise LanguageServerError(f"{method} could not reach Antigravity") from exc

        if not response_body:
            return {}
        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise LanguageServerError(f"{method} returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise LanguageServerError(f"{method} returned a non-object response")
        return result

    async def _rpc(self, method: str, payload: dict) -> dict:
        return await asyncio.to_thread(self._rpc_sync, method, payload)

    @staticmethod
    def _workspace_uri(workspace: str) -> str:
        if workspace.startswith("file://"):
            return workspace
        return Path(workspace).expanduser().resolve().as_uri()

    @staticmethod
    def _cascade_id(conversation_id: str | None) -> str:
        try:
            return str(uuid.UUID(conversation_id)) if conversation_id else str(uuid.uuid4())
        except (ValueError, AttributeError):
            return str(uuid.uuid4())

    @classmethod
    def _model_entries(cls, value, key: str | None = None):
        if isinstance(value, dict):
            enum_value = value.get("model")
            if key and isinstance(enum_value, str):
                yield key, enum_value
            for child_key, child in value.items():
                yield from cls._model_entries(child, child_key)
        elif isinstance(value, list):
            for child in value:
                yield from cls._model_entries(child)

    async def _resolve_model(self, model: str | None) -> str:
        if model and model.startswith("MODEL_"):
            return model

        response = await self._rpc("GetAvailableModels", {})
        entries = dict(self._model_entries(response))
        requested = (model or self._default_model).lower()
        candidates = [requested]
        if requested == "gemini-3.6-flash":
            candidates.extend(
                [
                    "gemini-3.6-flash-high",
                    "gemini-3.6-flash-medium",
                    "gemini-3.6-flash-low",
                ]
            )
        for candidate in candidates:
            if candidate in entries:
                return entries[candidate]

        raise LanguageServerError(f"Antigravity model is unavailable: {model or self._default_model}")

    async def run(
        self,
        prompt: str,
        workspace: str,
        conversation_id: str | None,
        model: str | None,
        profile: str | None,
    ) -> AgentAPIResult:
        del profile  # Profiles remain supervisor metadata; the bridge owns its tool policy.
        resolved_model = await self._resolve_model(model)
        requested_cascade_id = self._cascade_id(conversation_id)
        start = await self._rpc(
            "StartCascade",
            {
                "source": "CORTEX_TRAJECTORY_SOURCE_AGENT_API",
                "trajectoryType": "CORTEX_TRAJECTORY_TYPE_USER_MAINLINE",
                "cascadeId": requested_cascade_id,
                "requestedModel": resolved_model,
                "workspaceUris": [self._workspace_uri(workspace)],
            },
        )
        cascade_id = start.get("cascadeId", requested_cascade_id)
        await self._rpc(
            "SendUserCascadeMessage",
            {
                "cascadeId": cascade_id,
                "items": [{"text": prompt}],
                "cascadeConfig": {
                    "agentApiConfig": {"enabled": True},
                    "plannerConfig": {"planModel": resolved_model},
                },
                "blocking": True,
            },
        )
        response = await self._wait_for_response(cascade_id)
        return AgentAPIResult(conversation_id=cascade_id, response=response)

    async def _wait_for_response(self, cascade_id: str) -> str:
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            trajectory = await self._rpc("GetCascadeTrajectory", {"cascadeId": cascade_id})
            response = self._latest_response(trajectory)
            status = trajectory.get("status", "")
            if response is not None and status == "CASCADE_RUN_STATUS_IDLE":
                return response
            if status in {"CASCADE_RUN_STATUS_FAILED", "CASCADE_RUN_STATUS_ERROR"}:
                raise LanguageServerError(f"Antigravity cascade failed: {status}")
            if asyncio.get_running_loop().time() >= deadline:
                raise LanguageServerError("timed out waiting for Antigravity cascade")
            await asyncio.sleep(self.poll_interval)

    @staticmethod
    def _latest_response(trajectory: dict) -> str | None:
        steps = trajectory.get("trajectory", {}).get("steps", [])
        for step in reversed(steps):
            planner_response = step.get("plannerResponse", {})
            response = planner_response.get("modifiedResponse") or planner_response.get("response")
            if isinstance(response, str) and response.strip():
                return response.strip()
        return None
