.PHONY: help install run dev clean setup

# Default target
help:
	@echo "╔════════════════════════════════════════════╗"
	@echo "║     Shadow Project - Available Commands     ║"
	@echo "╚════════════════════════════════════════════╝"
	@echo ""
	@echo "Quick Start:"
	@echo "  make setup    → Install everything & run"
	@echo "  make run      → Run the application"
	@echo "  make dev      → Run in development mode with debug"
	@echo ""
	@echo "Individual Commands:"
	@echo "  make install  → Install/upgrade dependencies only"
	@echo "  make clean    → Remove virtual environment & cache"
	@echo "  make help     → Show this help message"
	@echo ""

# Setup: Install everything and run
setup: install run

# Install: Create venv and install dependencies
install:
	@echo "Setting up environment and installing dependencies..."
	@chmod +x install.sh
	@./install.sh

# Run: Start the application
run:
	@echo "Starting Shadow application..."
	@chmod +x run.sh
	@./run.sh

# Dev: Run in development mode with debug output
dev:
	@echo "Starting Shadow application (development mode)..."
	@chmod +x run.sh
	@./run.sh --dev

# Clean: Remove virtual environment and cache
clean:
	@echo "Cleaning up environment..."
	@rm -rf .venv
	@rm -rf __pycache__
	@rm -rf .pytest_cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo "✓ Cleanup complete"
