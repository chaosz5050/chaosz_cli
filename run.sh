#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}== Chaosz CLI Launcher ==${NC}"

# 1. Check for Poetry
if ! command -v poetry &> /dev/null; then
    echo -e "${YELLOW}Poetry is not installed.${NC}"
    read -p "Would you like to install Poetry now? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}Installing Poetry...${NC}"
        curl -sSL https://install.python-poetry.org | python3 -
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo -e "${RED}Poetry is required to run this application. Exiting.${NC}"
        exit 1
    fi
fi

# 2. Install dependencies via Poetry
echo -e "${GREEN}Installing dependencies...${NC}"
poetry install

# 3. Launch application
echo -e "${GREEN}Launching Chaosz CLI...${NC}"
poetry run chaosz
