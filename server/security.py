import os
import re
from google.antigravity import types
from google.antigravity.hooks import hooks

def get_enforce_boundaries_hook(profile: str, workspace: str):
    """
    Returns a pre_tool_call_decide hook customized for the given profile and workspace.
    """
    
    @hooks.pre_tool_call_decide
    async def enforce_worker_boundaries(tool_call: types.ToolCall) -> types.HookResult:
        tool_name = tool_call.name
        tool_args = tool_call.args or {}
        
        # 1. Profile Read-Only Enforcement
        if profile in ["scout", "reviewer"]:
            write_tools = ["write_to_file", "replace_file_content", "multi_replace_file_content"]
            if tool_name in write_tools:
                return types.HookResult(
                    allow=False, 
                    reason=f"SECURITY ENFORCEMENT: Profile '{profile}' is read-only. Tool '{tool_name}' is blocked."
                )
                
        # 2. Workspace Scope Enforcement
        if profile == "worker" and workspace:
            if tool_name in ["write_to_file", "replace_file_content", "multi_replace_file_content"]:
                target = tool_args.get("TargetFile") or tool_args.get("path", "")
                if target:
                    if not os.path.isabs(target):
                        target = os.path.join(workspace, target)
                    abs_target = os.path.realpath(target)
                    abs_scope = os.path.realpath(workspace)
                    if os.path.commonpath([abs_scope, abs_target]) != abs_scope:
                        return types.HookResult(
                            allow=False,
                            reason=f"SECURITY ENFORCEMENT: Writing outside workspace '{workspace}' to '{target}' is forbidden."
                        )

        # 3. VCS Protection and OS Sandboxing
        if tool_name == "run_command":
            # Prevent OS Sandbox Bypass for all profiles
            if tool_args.get("BypassSandbox"):
                return types.HookResult(
                    allow=False,
                    reason="SECURITY ENFORCEMENT: Subordinate workers are not allowed to bypass the OS sandbox."
                )
                
            cmd = tool_args.get("CommandLine") or tool_args.get("command", "")
            
            import shlex
            try:
                tokens = shlex.split(cmd)
            except ValueError:
                return types.HookResult(
                    allow=False,
                    reason=f"SECURITY ENFORCEMENT: Malformed command string '{cmd}'."
                )
                
            cmd_lower = cmd.lower()
            
            # Check for destructive git operations
            if "git " in cmd_lower or cmd_lower.startswith("git"):
                if any(t in tokens for t in ["commit", "push", "merge", "reset", "clean"]):
                    return types.HookResult(
                        allow=False,
                        reason=f"SECURITY ENFORCEMENT: Destructive git operation in '{cmd}' is blocked for subordinate workers."
                    )
                    
            # Check for recursive force removal (including full paths and subshells)
            if re.search(r'(?:\b|/)(rm|rmdir)\b', cmd_lower):
                if re.search(r'-[a-z]*r', cmd_lower) and re.search(r'-[a-z]*f', cmd_lower):
                    return types.HookResult(
                        allow=False,
                        reason=f"SECURITY ENFORCEMENT: Destructive command '{cmd}' is blocked for subordinate workers."
                    )
                
        return types.HookResult(allow=True)
        
    return enforce_worker_boundaries
