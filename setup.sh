#!/bin/bash
set -e

# Colors
GREEN='\033[38;2;68;187;102m'
RESET='\033[0m'

clear
echo ""
echo -e "${GREEN}"
cat << "EOF"
  ██████╗██╗  ██╗ █████╗  ██████╗ ███████╗███████╗
 ██╔════╝██║  ██║██╔══██╗██╔═══██╗██╔════╝╚══███╔╝
 ██║     ███████║███████║██║   ██║███████╗  ███╔╝
 ██║     ██╔══██║██╔══██║██║   ██║╚════██║ ███╔╝
 ╚██████╗██║  ██║██║  ██║╚██████╔╝███████║███████╗
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝
        C L I  —  Plug in a brain. Own the chaos.
EOF
echo -e "${RESET}"

echo "[CHECK] Starting Chaosz CLI setup..."

# 1. Python Check
echo "[CHECK] Verifying Python version..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "Python 3 is not installed. Please install Python 3.11 or higher."
    exit 1
fi

PY_VERSION=$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if ! $PYTHON_CMD -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
    echo "Python version $PY_VERSION is too old. Please install Python 3.11 or higher."
    exit 1
fi
echo "[CHECK] Python $PY_VERSION found."

# 2. Dependency Check: pipx
if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx is not installed."
    read -p "Would you like to install pipx now? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm pipx
        elif command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y pipx
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y pipx
        elif command -v brew >/dev/null 2>&1; then
            brew install pipx
        else
            echo "Could not detect package manager. Please install pipx manually."
            exit 1
        fi
    else
        echo "pipx is required to install Chaosz globally. Exiting."
        exit 1
    fi
else
    echo "[CHECK] pipx found."
fi

# 3. Environment Setup
echo "[INSTALLING] Setting up user directories..."
CHAOSZ_DIR="$HOME/.config/chaosz"
LOGS_DIR="$CHAOSZ_DIR/logs"

mkdir -p "$LOGS_DIR"
chmod 700 "$CHAOSZ_DIR"
chmod 700 "$LOGS_DIR"
echo "[CHECK] Created $LOGS_DIR and set permissions."

# 4. Optional: Node.js check (needed only for npm-based MCP servers like npx -y @modelcontextprotocol/...)
if command -v node >/dev/null 2>&1 && command -v npx >/dev/null 2>&1; then
    echo "[CHECK] Node.js $(node --version) and npx found — npm-based MCP servers are supported."
else
    echo "[INFO] Node.js / npx not found. This is optional — only needed if you plan to use"
    echo "       npm-based MCP servers (e.g. npx -y @modelcontextprotocol/server-filesystem)."
    echo "       Python and SSE-based MCP servers work without Node.js."
fi

# 4b. The Install
echo "[INSTALLING] Installing Chaosz CLI globally via pipx..."
pipx install . --force

# 5. Path Verification
echo "[CHECK] Verifying pipx path..."
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "The pipx bin directory (~/.local/bin) is not in your PATH."
    read -p "Would you like to run 'pipx ensurepath' to fix this? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pipx ensurepath
        echo "Please restart your terminal or run 'source ~/.bashrc' (or equivalent) to apply path changes."
    fi
fi

echo "[DONE] Chaosz CLI has been installed successfully! You can now run 'chaosz' from anywhere."
