#!/usr/bin/env python3
"""Unified entrypoint for the source-first 1C context toolkit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COMMAND_TO_SCRIPT = {
    "init": REPO_ROOT / "scripts" / "init_workspace.py",
    "install-agent": REPO_ROOT / "scripts" / "install_agent.py",
    "status": REPO_ROOT / "scripts" / "status_workspace.py",
    "verify": REPO_ROOT / "tools" / "verify_local_kb.py",
    "export": REPO_ROOT / "scripts" / "export_skill_bundle.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="1C source-first local context toolkit")
    parser.add_argument("command", choices=sorted(COMMAND_TO_SCRIPT))
    args, rest = parser.parse_known_args()
    script = COMMAND_TO_SCRIPT[args.command]
    return subprocess.call([sys.executable, str(script), *rest])


if __name__ == "__main__":
    raise SystemExit(main())
