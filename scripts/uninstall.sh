#!/usr/bin/env bash
echo "=== Uninstalling Codex Gemini Delegator ==="

echo "Removing Antigravity companion plugin..."
rm -rf "$HOME/.gemini/config/plugins/codex-supervised-worker"

echo "The ledger database and logs at ~/.codex/gemini-delegator have been preserved."
echo "If you wish to remove them completely, run: rm -rf ~/.codex/gemini-delegator"
echo ""
echo "Please remember to remove the plugin and mcp_server entries from your ~/.codex/config.toml manually."
echo "Uninstallation complete."
