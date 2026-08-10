import os
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
                    abs_target = os.path.realpath(target)
                    abs_scope = os.path.realpath(workspace)
                    if os.path.commonpath([abs_scope, abs_target]) != abs_scope:
                        return types.HookResult(
                            allow=False,
                            reason=f"SECURITY ENFORCEMENT: Writing outside workspace '{workspace}' to '{target}' is forbidden."
                        )

        # 3. VCS Protection
        if tool_name == "run_command":
            cmd = tool_args.get("CommandLine") or tool_args.get("command", "")
            blocked = ["git commit", "git push", "git merge", "git reset", "git clean", "rm -rf"]
            if any(b in cmd for b in blocked):
                return types.HookResult(
                    allow=False,
                    reason=f"SECURITY ENFORCEMENT: Destructive command '{cmd}' is blocked for subordinate workers."
                )
                
        return types.HookResult(allow=True)
        
    return enforce_worker_boundaries
