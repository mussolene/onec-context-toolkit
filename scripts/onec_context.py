#!/usr/bin/env python3
"""Unified entrypoint for the source-first 1C context toolkit."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COMMAND_TO_SCRIPT = {
    "bootstrap": REPO_ROOT / "scripts" / "bootstrap.py",
    "init": REPO_ROOT / "scripts" / "init_workspace.py",
    "install-agent": REPO_ROOT / "scripts" / "install_agent.py",
    "status": REPO_ROOT / "scripts" / "status_workspace.py",
    "verify": REPO_ROOT / "tools" / "verify_local_kb.py",
    "export": REPO_ROOT / "scripts" / "export_skill_bundle.py",
}


def _print_help() -> None:
    commands = ",".join(sorted(COMMAND_TO_SCRIPT))
    print("usage: onec_context.py [-h] {" + commands + "} ...")
    print()
    print("1C source-first local context toolkit")
    print()
    print("commands:")
    for name in sorted(COMMAND_TO_SCRIPT):
        print(f"  {name}")


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        _print_help()
        return 0
    command = argv[0]
    script = COMMAND_TO_SCRIPT.get(command)
    if script is None:
        print(f"unknown command: {command}", file=sys.stderr)
        _print_help()
        return 2
    return subprocess.call([sys.executable, str(script), *argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
