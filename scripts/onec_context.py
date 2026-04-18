#!/usr/bin/env python3
"""Unified entrypoint for the source-first 1C context toolkit."""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COMMAND_TO_SCRIPT = {
    "bootstrap": REPO_ROOT / "scripts" / "bootstrap.py",
    "doctor": REPO_ROOT / "scripts" / "doctor.py",
    "ensure": REPO_ROOT / "scripts" / "ensure_workspace.py",
    "resolve-packs": REPO_ROOT / "scripts" / "resolve_packs.py",
    "init": REPO_ROOT / "scripts" / "init_workspace.py",
    "install-agent": REPO_ROOT / "scripts" / "install_agent.py",
    "status": REPO_ROOT / "scripts" / "status_workspace.py",
    "verify": REPO_ROOT / "tools" / "verify_local_kb.py",
    "benchmark": REPO_ROOT / "tools" / "benchmark_local_kb.py",
    "query-kb": REPO_ROOT / "tools" / "local_kb_query.py",
    "query-code": REPO_ROOT / "tools" / "query_code_pack.py",
    "query-config": REPO_ROOT / "tools" / "query_config_pack.py",
    "export": REPO_ROOT / "scripts" / "export_skill_bundle.py",
}

COMMAND_DESCRIPTIONS = {
    "benchmark": "measure query latency for built packs",
    "bootstrap": "install local Python dependencies for the toolkit",
    "doctor": "check host prerequisites and optional HBK helpers",
    "ensure": "build an extra workspace layer only when needed",
    "export": "export a read-only skill bundle from an initialized workspace",
    "init": "initialize a workspace and build the base help layer",
    "install-agent": "install the self-contained skill bundle into an agent",
    "query-code": "query the code pack for modules, symbols, calls, and callers",
    "query-config": "query the full lossless config pack",
    "query-kb": "query platform or metadata knowledge packs",
    "resolve-packs": "show exact pack paths and available targets for a workspace",
    "status": "check workspace state and detect stale or missing packs",
    "verify": "run smoke checks against the current workspace packs",
}


def _print_help() -> None:
    commands = ",".join(sorted(COMMAND_TO_SCRIPT))
    print("usage: onec-context [-h] {" + commands + "} ...")
    print()
    print("1C source-first local context toolkit")
    print()
    print("quick start:")
    print("  1. onec-context doctor --workspace-init --hbk-base <HBK_ROOT>")
    print("  2. onec-context init --workspace-root <repo> --source-path <source> --profile base --hbk-base <HBK_ROOT> --platform <VERSION>")
    print("  3. onec-context ensure --workspace-root <repo> --need metadata|code|full  # only when needed")
    print()
    print("commands:")
    for name in sorted(COMMAND_TO_SCRIPT):
        print(f"  {name:<14} {COMMAND_DESCRIPTIONS[name]}")


def _venv_python() -> Path:
    if os.name == "nt":
        return REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return REPO_ROOT / ".venv" / "bin" / "python"


def _ensure_local_runtime() -> Path:
    python_bin = _venv_python()
    if python_bin.is_file():
        return python_bin
    if os.environ.get("ONEC_CONTEXT_SKIP_AUTO_BOOTSTRAP") == "1":
        return Path(sys.executable)
    bootstrap_script = REPO_ROOT / "scripts" / "bootstrap.py"
    env = dict(os.environ)
    env["ONEC_CONTEXT_SKIP_AUTO_BOOTSTRAP"] = "1"
    subprocess.run([sys.executable, str(bootstrap_script), "--deps-only"], check=True, env=env)
    if python_bin.is_file():
        return python_bin
    return Path(sys.executable)


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
    python_bin = Path(sys.executable) if command == "bootstrap" else _ensure_local_runtime()
    return subprocess.call([str(python_bin), str(script), *argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
