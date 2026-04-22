#!/usr/bin/env python3
"""Bootstrap the toolkit for first-run local use."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = REPO_ROOT / ".venv"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _is_absolute_path_like(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if text.startswith("http://") or text.startswith("https://"):
        return False
    if text.startswith("/"):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", text))


def _public_payload(payload: object) -> object:
    if isinstance(payload, dict):
        return {k: _public_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_public_payload(x) for x in payload]
    if isinstance(payload, str) and _is_absolute_path_like(payload):
        return "<redacted-path>"
    return payload


def ensure_venv(venv_dir: Path) -> Path:
    python_bin = _venv_python(venv_dir)
    if python_bin.is_file():
        return python_bin
    _run([sys.executable, "-m", "venv", str(venv_dir)])
    return python_bin


def ensure_local_install(python_bin: Path) -> None:
    _run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(python_bin), "-m", "pip", "install", "-e", str(REPO_ROOT)])


def bootstrap(args: argparse.Namespace) -> dict[str, object]:
    venv_dir = Path(args.venv_dir).expanduser().resolve()
    python_bin = ensure_venv(venv_dir)
    ensure_local_install(python_bin)
    if args.deps_only:
        return {
            "repo_root": str(REPO_ROOT),
            "venv_dir": str(venv_dir),
            "python_bin": str(python_bin),
            "deps_only": True,
        }
    doctor_cmd = [str(python_bin), str(REPO_ROOT / "scripts" / "doctor.py")]
    if args.workspace_root:
        doctor_cmd.append("--workspace-init")
    if args.hbk_base:
        doctor_cmd.extend(["--hbk-base", args.hbk_base])
    _run(doctor_cmd)

    result: dict[str, object] = {
        "repo_root": str(REPO_ROOT),
        "venv_dir": str(venv_dir),
        "python_bin": str(python_bin),
        "agent": None,
        "workspace_root": None,
        "profile": args.profile,
    }

    if args.agent:
        install_cmd = [
            str(python_bin),
            str(REPO_ROOT / "scripts" / "install_agent.py"),
            "--agent",
            args.agent,
        ]
        if args.skill_name:
            install_cmd.extend(["--skill-name", args.skill_name])
        if args.workspace:
            install_cmd.extend(["--workspace", args.workspace])
        _run(install_cmd)
        result["agent"] = args.agent

    if args.workspace_root:
        init_cmd = [
            str(python_bin),
            str(REPO_ROOT / "scripts" / "init_workspace.py"),
            "--workspace-root",
            args.workspace_root,
            "--source-path",
            args.source_path or args.workspace_root,
            "--profile",
            args.profile,
        ]
        if args.source_kind:
            init_cmd.extend(["--source-kind", args.source_kind])
        if args.metadata_source:
            init_cmd.extend(["--metadata-source", args.metadata_source])
        if args.hbk_base:
            init_cmd.extend(["--hbk-base", args.hbk_base])
        for version in args.platform or []:
            init_cmd.extend(["--platform", version])
        for base_config in args.base_config or []:
            init_cmd.extend(["--base-config", base_config])
        if args.with_metadata:
            init_cmd.append("--with-metadata")
        if args.with_code:
            init_cmd.append("--with-code")
        if args.with_full_pack:
            init_cmd.append("--with-full-pack")
        if args.with_standards:
            init_cmd.append("--with-standards")
        if args.standards_dir:
            init_cmd.extend(["--standards-dir", args.standards_dir])
        if args.fetch_its_standards:
            init_cmd.append("--fetch-its-standards")
        if args.without_help:
            init_cmd.append("--without-help")
        _run(init_cmd)
        result["workspace_root"] = str(Path(args.workspace_root).expanduser().resolve())

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap local toolkit, install an agent skill, and optionally initialize a workspace")
    parser.add_argument("--venv-dir", default=str(DEFAULT_VENV), help="Local virtualenv directory for this repo or installed skill bundle")
    parser.add_argument("--deps-only", action="store_true", help="Only provision the local virtualenv and Python dependencies")
    parser.add_argument("--agent", choices=["codex", "claude", "cursor"], help="Optional agent integration to install")
    parser.add_argument("--skill-name", default="onec-context", help="Skill name for Codex/Claude")
    parser.add_argument("--workspace", default=".", help="Cursor workspace target when --agent cursor is used")
    parser.add_argument("--workspace-root", default=None, help="Optional workspace to initialize after dependencies are ready")
    parser.add_argument("--source-path", default=None, help="Optional source root for workspace initialization")
    parser.add_argument("--source-kind", default="auto", choices=["auto", "configdump", "extension", "metadata-export"])
    parser.add_argument("--profile", default="base", choices=["base", "metadata", "dev", "full"])
    parser.add_argument("--metadata-source", default=None)
    parser.add_argument("--hbk-base", default=None)
    parser.add_argument("--platform", action="append", default=[])
    parser.add_argument("--base-config", action="append", default=[])
    parser.add_argument("--with-metadata", action="store_true")
    parser.add_argument("--with-code", action="store_true")
    parser.add_argument("--with-full-pack", action="store_true")
    parser.add_argument("--with-standards", action="store_true")
    parser.add_argument("--standards-dir", default=None)
    parser.add_argument("--fetch-its-standards", action="store_true")
    parser.add_argument("--without-help", action="store_true")
    args = parser.parse_args()

    result = bootstrap(args)
    print(json.dumps(_public_payload(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
