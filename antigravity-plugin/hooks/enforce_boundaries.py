#!/usr/bin/env python3
import sys
import os
import json

def main():
    # Only enforce if this process is a Codex supervised worker
    if os.environ.get("CODEX_SUPERVISED_WORKER") != "1":
        sys.exit(0)

    try:
        input_data = sys.stdin.read()
        if not input_data:
            sys.exit(0)
            
        request = json.loads(input_data)
        tool_name = request.get("tool_name", "")
        tool_args = request.get("tool_args", {})
        
        profile = os.environ.get("CODEX_SUPERVISED_PROFILE", "worker")
        scope = os.environ.get("CODEX_SUPERVISED_SCOPE", "")
        model = os.environ.get("CODEX_SUPERVISED_MODEL", "").lower()
        
        # Enforce Subagent Deployment (Only PRO is allowed)
        if tool_name in ["invoke_subagent", "define_subagent"]:
            if "pro" not in model:
                print(json.dumps({
                    "allowed": False,
                    "reason": f"SECURITY ENFORCEMENT: Your model tier ({model}) is not authorized to deploy sub-sub agents. Only 'pro' models can be sub-foremen."
                }))
                sys.exit(1)
        
        # Deny all structural VCS operations
        if tool_name == "run_command":
            cmd = tool_args.get("CommandLine", "")
            dangerous_cmds = ["git commit", "git push", "git merge", "git reset", "git clean", "rm -rf"]
            for d in dangerous_cmds:
                if d in cmd:
                    print(json.dumps({
                        "allowed": False,
                        "reason": f"SECURITY ENFORCEMENT: Command '{d}' is blocked for subordinate workers. You cannot commit, push, or run destructive git operations."
                    }))
                    sys.exit(1)
                    
        # Enforce Read-Only Profiles
        if profile in ["scout", "reviewer"]:
            write_tools = ["write_to_file", "replace_file_content", "multi_replace_file_content", "run_command"]
            if tool_name in write_tools:
                if tool_name == "run_command":
                    # Allow safe read-only commands for scouts if they don't mutate state (approximate check)
                    cmd = tool_args.get("CommandLine", "")
                    if any(c in cmd for c in ["cat ", "ls ", "grep ", "find ", "rg "]) and ">" not in cmd and "|" not in cmd:
                        sys.exit(0)
                
                print(json.dumps({
                    "allowed": False,
                    "reason": f"SECURITY ENFORCEMENT: Your profile ({profile}) is strictly read-only. You cannot use {tool_name}."
                }))
                sys.exit(1)
                
        # Enforce Workspace Scope for Write Profiles
        if profile == "worker" and scope:
            write_tools = ["write_to_file", "replace_file_content", "multi_replace_file_content"]
            if tool_name in write_tools:
                target_file = tool_args.get("TargetFile", "")
                if target_file:
                    abs_target = os.path.realpath(target_file)
                    abs_scope = os.path.realpath(scope)
                    if os.path.commonpath([abs_scope, abs_target]) != abs_scope:
                        print(json.dumps({
                            "allowed": False,
                            "reason": f"SECURITY ENFORCEMENT: You are only allowed to modify files within '{scope}'. Attempted to write outside scope: {target_file}"
                        }))
                        sys.exit(1)

        # Allow if no restrictions matched
        print(json.dumps({"allowed": True}))
        sys.exit(0)
        
    except Exception as e:
        print(json.dumps({"allowed": False, "reason": f"Hook execution failed: {e}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
