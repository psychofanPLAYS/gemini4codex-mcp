#!/usr/bin/env bash
set -e

echo "=== Installing Codex Gemini Delegator ==="

# 1. Check prerequisites
if ! command -v codex &> /dev/null; then
    echo "❌ Error: 'codex' command not found."
    exit 1
fi

if ! command -v gemini &> /dev/null; then
    echo "❌ Error: 'gemini' (Antigravity CLI) command not found."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Error: 'python3' command not found."
    exit 1
fi

echo "✅ Prerequisites met."

# 2. Setup environment
echo "Setting up Python environment and dependencies..."
python3 -m pip install -q "mcp>=1.0.0"

# 3. Setup state directory
echo "Setting up state directory..."
mkdir -p ~/.codex/gemini-delegator/logs

# 4. Install Antigravity Companion Plugin
echo "Installing Antigravity companion plugin..."
AGY_PLUGIN_DIR="$HOME/.gemini/config/plugins/codex-supervised-worker"
mkdir -p "$AGY_PLUGIN_DIR"
cp -r ../antigravity-plugin/* "$AGY_PLUGIN_DIR/"
chmod +x "$AGY_PLUGIN_DIR/hooks/enforce_boundaries.py"

# 5. Codex Plugin Setup Guidance
echo ""
echo "=== Manual Setup Required for Codex Plugin ==="
echo "To finish installation, you need to register the Codex plugin."
echo "Since local marketplace structures vary, the easiest way is to add this block to your ~/.codex/config.toml:"
echo ""
echo "[plugins.\"gemini-delegator@local\"]"
echo "enabled = true"
echo ""
echo "And map it in your local marketplaces section pointing to: $(pwd)/../plugin"
echo "Alternatively, add the MCP server directly to ~/.codex/config.toml:"
echo ""
echo "[mcp_servers.gemini-delegator]"
echo "command = \"python3\""
echo "args = [\"-m\", \"gemini_delegator\"]"
echo "cwd = \"$(pwd)/../server\""
echo "env = { PYTHONPATH = \"$(pwd)/../server\" }"
echo ""
echo "Installation structure prepared successfully!"
