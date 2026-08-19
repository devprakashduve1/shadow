#!/bin/bash

###############################################################################
# Run Script: Execute Shadow Application with Single Command
#
# Usage: ./run.sh [--install] [--dev]
#
# Options:
#   --install    First time setup (installs dependencies)
#   --dev        Run in development mode with debug output
#
# This script:
# 1. Checks/creates virtual environment
# 2. Installs/upgrades dependencies (if --install)
# 3. Activates virtual environment
# 4. Runs the main application
###############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Directories
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"

# Flags
INSTALL_MODE=false
DEV_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --install)
            INSTALL_MODE=true
            shift
            ;;
        --dev)
            DEV_MODE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Usage: ./run.sh [--install] [--dev]"
            exit 1
            ;;
    esac
done

# Header
echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Shadow Project - Application Launcher     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: Check Python
echo -e "${YELLOW}[1/4]${NC} Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python3 not found. Please install Python 3.8+${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✓${NC} $PYTHON_VERSION"
echo ""

# Step 2: Setup virtual environment
echo -e "${YELLOW}[2/4]${NC} Setting up virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
echo -e "${GREEN}✓${NC} Virtual environment ready"
echo ""

# Step 3: Install/upgrade dependencies if needed
if [ "$INSTALL_MODE" = true ]; then
    echo -e "${YELLOW}[3/4]${NC} Installing dependencies..."
    pip install --upgrade pip setuptools wheel > /dev/null 2>&1
    pip install -r "$PROJECT_DIR/requirements.txt"
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    # Quick check for missing packages
    echo -e "${YELLOW}[3/4]${NC} Checking dependencies..."
    if python3 -c "import PyQt6" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Core dependencies present"
    else
        echo -e "${YELLOW}⚠${NC} Missing dependencies. Run: ./run.sh --install"
        exit 1
    fi
fi
echo ""

# Step 4: Launch application
echo -e "${YELLOW}[4/4]${NC} Launching application..."
echo ""

# Set up environment variables for development mode
if [ "$DEV_MODE" = true ]; then
    export DEBUG=1
    export PYTHONUNBUFFERED=1
    echo -e "${YELLOW}Debug mode enabled${NC}"
    echo ""
fi

# Run the application
cd "$PROJECT_DIR"
python3 main.py

# Cleanup (executed after app closes)
echo ""
echo -e "${BLUE}Application closed${NC}"
