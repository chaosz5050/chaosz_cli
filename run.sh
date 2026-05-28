#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}== Chaosz CLI Launcher ==${NC}"

# 1. Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv is not installed.${NC}"
    read -p "Would you like to install uv now? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}Installing uv...${NC}"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo -e "${RED}uv is required to run this application. Exiting.${NC}"
        exit 1
    fi
fi

# 2. Install dependencies via uv
echo -e "${GREEN}Installing dependencies...${NC}"
uv sync

# 3. Launch application
echo -e "${GREEN}Launching Chaosz CLI...${NC}"
uv run chaosz
