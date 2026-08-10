#!/usr/bin/env bash

echo "=== Codex Gemini Delegator Doctor ==="

# Check Codex
if command -v codex &> /dev/null; then
    echo "✅ Codex CLI found: $(codex --version)"
else
    echo "❌ Codex CLI not found."
fi

# Check Gemini CLI
if command -v gemini &> /dev/null; then
    echo "✅ Gemini CLI found: $(gemini --version)"
else
    echo "❌ Gemini CLI not found."
fi

# Check Python and MCP
if python3 -c "import mcp" &> /dev/null; then
    echo "✅ Python MCP SDK found."
else
    echo "❌ Python MCP SDK not found. Run: pip install mcp"
fi

# Check DB
DB_PATH="$HOME/.codex/gemini-delegator/ledger.db"
if [ -f "$DB_PATH" ]; then
    echo "✅ SQLite ledger found at $DB_PATH"
else
    echo "⚠️ SQLite ledger not initialized yet. It will be created on first run."
fi

# Check Antigravity Plugin
AGY_PLUGIN_DIR="$HOME/.gemini/config/plugins/codex-supervised-worker"
if [ -d "$AGY_PLUGIN_DIR" ]; then
    echo "✅ Antigravity companion plugin installed at $AGY_PLUGIN_DIR"
else
    echo "❌ Antigravity companion plugin missing. Run install.sh"
fi

echo "Doctor check complete."
