#!/bin/bash

###############################################################################
# Setup Script: Install Environment and Dependencies
#
# Usage: ./install.sh
#
# This script:
# 1. Creates/activates Python virtual environment
# 2. Installs all required dependencies
# 3. Verifies installation
###############################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

# Directories
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Shadow Project - Environment Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Check Python
echo -e "${YELLOW}[1/5]${NC} Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python3 not found${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✓${NC} $PYTHON_VERSION found"
echo ""

# Step 2: Create/activate virtual environment
echo -e "${YELLOW}[2/5]${NC} Setting up virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    echo -e "  Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} Virtual environment created"
else
    echo -e "${GREEN}✓${NC} Virtual environment already exists"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"
echo -e "${GREEN}✓${NC} Virtual environment activated"
echo ""

# Step 3: Upgrade pip and setuptools
echo -e "${YELLOW}[3/5]${NC} Upgrading pip and setuptools..."
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
echo -e "${GREEN}✓${NC} pip and setuptools upgraded"
echo ""

# Step 4: Install requirements
echo -e "${YELLOW}[4/5]${NC} Installing dependencies from requirements.txt..."
if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
    echo -e "${RED}✗ requirements.txt not found${NC}"
    exit 1
fi

pip install -r "$PROJECT_DIR/requirements.txt"
echo -e "${GREEN}✓${NC} Dependencies installed"
echo ""

# Step 5: Verify installation
echo -e "${YELLOW}[5/5]${NC} Verifying installation..."
python3 -c "import PyQt6; import cv2; import mediapipe" 2>/dev/null && \
    echo -e "${GREEN}✓${NC} All core packages verified" || \
    echo -e "${YELLOW}⚠${NC} Some packages may need additional setup"
echo ""

# Final status
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Next step: Run the application with:"
echo -e "  ${YELLOW}./run.sh${NC}"
echo ""
