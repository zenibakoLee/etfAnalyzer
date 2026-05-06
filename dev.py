"""
Development runner — auto-restarts the bot when source files change.
Usage: python dev.py
"""
from watchfiles import run_process

if __name__ == "__main__":
    print("Starting ETF bot in dev mode (auto-restart on file changes)...")
    run_process("src/", target="src.main", target_type="module")
