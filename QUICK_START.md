# Shadow Project - Quick Start Guide

**Welcome to Shadow!** Get the entire application running with a single command.

---

## 🚀 First Time Setup

### Option 1: One Command (Recommended)
```bash
make setup
```
This installs everything and starts the app automatically.

### Option 2: Step by Step
```bash
# 1. Install dependencies
make install
# or: ./install.sh

# 2. Run the application
make run
# or: ./run.sh
```

---

## ⚡ Quick Commands

| Command | Purpose |
|---------|---------|
| `make setup` | **FIRST TIME ONLY** — Install + Run |
| `make run` | Start the application |
| `make dev` | Run with debug output (development) |
| `make install` | Install/upgrade dependencies only |
| `make clean` | Remove virtual environment & cache |
| `make help` | Show all available commands |

---

## 🛠️ Advanced Usage

### Using `./run.sh` Directly
```bash
# First time (with installation)
./run.sh --install

# Subsequent runs (uses existing environment)
./run.sh

# Development mode with debug output
./run.sh --dev
```

### Using `./install.sh` Directly
```bash
# One-time environment setup
./install.sh
```

---

## 📋 What Happens

### `make setup` (or `make install` then `make run`)
1. ✅ Checks Python 3 installation
2. ✅ Creates virtual environment (`.venv`)
3. ✅ Upgrades pip & setuptools
4. ✅ Installs all dependencies from `requirements.txt`
5. ✅ Verifies core packages
6. ✅ Launches the PyQt6 application

### Environment Activation
- Scripts automatically activate the virtual environment
- No manual `source .venv/bin/activate` needed
- Environment persists during app runtime

---

## ❌ Troubleshooting

### "Python3 not found"
**Fix:** Install Python 3.8+
```bash
# macOS
brew install python3

# Linux (Ubuntu/Debian)
sudo apt-get install python3

# Windows
# Download from https://www.python.org/downloads/
```

### "Missing required packages"
**Fix:** Reinstall dependencies
```bash
make clean
make setup
```

### App crashes on startup
**Fix:** Check for errors
```bash
# Run with debug output
./run.sh --dev

# Verify packages
python3 -c "import PyQt6; import cv2; import mediapipe"
```

### Port already in use (if using web interface)
**Fix:** Kill existing process
```bash
# Find process on port 8000
lsof -i :8000

# Kill it (replace PID with actual process ID)
kill -9 <PID>
```

---

## 📁 Project Structure

```
shadow/
├── Makefile              ← Use 'make' commands
├── install.sh            ← Environment setup
├── run.sh                ← Application launcher
├── main.py               ← Entry point
├── requirements.txt      ← Dependencies
├── gui/                  ← PyQt6 interface
├── assistant/            ← AI code editor
└── README.md             ← Full documentation
```

---

## 🎯 Next Steps

1. **First run:** `make setup`
2. **Subsequent runs:** `make run` or `./run.sh`
3. **Development:** `make dev` for debug output
4. **Full docs:** See `README.md` for complete documentation

---

## 💡 Tips

- **Faster startup:** Don't use `--install` on every run
- **Keep environment:** `.venv` directory is safe to keep
- **Update dependencies:** `make install` to reinstall
- **Clean slate:** `make clean` removes everything (safe to re-setup)

---

## 🔧 Environment Details

### Virtual Environment Location
- `.venv/` directory in project root
- Automatically created by `install.sh`
- Reused on subsequent runs

### Python Version Required
- Python 3.8 minimum
- Python 3.10+ recommended

### Key Dependencies
- PyQt6 (GUI framework)
- OpenCV (computer vision)
- MediaPipe (AI models)
- Various helper utilities

---

**Status**: ✅ Ready to Use  
**Last Updated**: 2026-08-06  
**Support**: Check `README.md` for detailed documentation
