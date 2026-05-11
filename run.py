#!/usr/bin/env python3
"""
OpenClaw Bot Launcher
Usage: python run.py [bot|api|all]

Environment variables (see .env.example):
- TELEGRAM_BOT_TOKEN: Required for bot
- API_KEY: Optional, for API authentication
"""

import os
import sys
import signal
import subprocess
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_env():
    """Load environment from .env file."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
    
    # Also load .env.chatwoot for backward compatibility
    env_chatwoot = PROJECT_ROOT / ".env.chatwoot"
    if env_chatwoot.exists():
        with open(env_chatwoot) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


def check_requirements():
    """Check required dependencies."""
    required = ["TELEGRAM_BOT_TOKEN"]
    missing = [r for r in required if not os.environ.get(r)]
    
    if missing:
        print(f"⚠️  Warning: Missing env variables: {', '.join(missing)}")
        print("   Set these in .env or environment")
    
    return len(missing) == 0


def run_bot():
    """Run Telegram bot."""
    print("🤖 Starting OpenClaw Bot...")
    bot_script = PROJECT_ROOT / "parse_bot_v6.py"
    python = PROJECT_ROOT / "venv_parse" / "bin" / "python"
    subprocess.run([str(python), str(bot_script)])


def run_api():
    """Run FastAPI server."""
    print("🌐 Starting OpenClaw API...")
    api_script = PROJECT_ROOT / "avito-parser-api" / "main.py"
    python = PROJECT_ROOT / "venv_parse" / "bin" / "python"
    subprocess.run([str(python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001"], 
                   cwd=PROJECT_ROOT / "avito-parser-api")


def run_all():
    """Run both bot and API."""
    import multiprocessing
    
    # Run API in separate process
    api_proc = multiprocessing.Process(target=run_api, name="OpenClaw-API")
    api_proc.start()
    
    # Run bot in main process
    try:
        run_bot()
    finally:
        api_proc.terminate()
        api_proc.join()


def main():
    parser = argparse.ArgumentParser(description="OpenClaw Bot Launcher")
    parser.add_argument(
        "target",
        choices=["bot", "api", "all"],
        nargs="?",
        default="bot",
        help="What to run: bot, api, or all (default: bot)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check configuration and exit"
    )
    
    args = parser.parse_args()
    
    # Load environment
    load_env()
    
    if args.check:
        check_requirements()
        print("✅ Configuration check passed")
        return
    
    # Check minimal requirements
    if args.target == "bot":
        if not check_requirements():
            print("\n❌ Please configure .env file before running")
            print(f"   cp .env.example .env")
            sys.exit(1)
    
    # Run requested target
    if args.target == "bot":
        run_bot()
    elif args.target == "api":
        run_api()
    elif args.target == "all":
        run_all()


if __name__ == "__main__":
    main()