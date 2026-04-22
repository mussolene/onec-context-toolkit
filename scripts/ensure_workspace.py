#!/usr/bin/env python3
"""Ensure a workspace has the requested layers built."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.workspace_manifest import init_args_from_manifest, load_workspace_manifest  # noqa: E402


PROFILE_ORDER = {
    "base": 0,
    "metadata": 1,
    "dev": 2,
    "full": 3,
}

NEED_TO_PROFILE = {
    "platform": "base",
    "standards": "base",
    "metadata": "metadata",
    "code": "dev",
    "full": "full",
}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _run_capture_ok(cmd: list[str]) -> bool:
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


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


def _desired_profile(current_profile: str, needs: list[str]) -> str:
    desired = current_profile if current_profile in PROFILE_ORDER else "base"
    for need in needs:
        candidate = NEED_TO_PROFILE[need]
        if PROFILE_ORDER[candidate] > PROFILE_ORDER[desired]:
            desired = candidate
    return desired


def _manifest_exists(workspace_root: Path) -> bool:
    return (workspace_root.expanduser().resolve() / ".onec" / "workspace.manifest.json").is_file()


def _manifest_satisfies_needs(manifest: dict[str, object], workspace_root: Path, needs: list[str]) -> bool:
    packs = manifest.get("packs") or {}
    if not isinstance(packs, dict):
        packs = {}
    targets = manifest.get("targets") or {}
    if not isinstance(targets, dict):
        targets = {}

    for need in needs:
        if need in {"platform", "standards"}:
            path_value = packs.get("platform")
            if need == "standards":
                path_value = packs.get("standards")
            if not isinstance(path_value, str) or not Path(path_value).expanduser().resolve().is_file():
                return False
            continue
        if not targets:
            path_value = packs.get(need)
            if not isinstance(path_value, str) or not Path(path_value).expanduser().resolve().is_file():
                return False
            continue
        for payload in targets.values():
            target_packs = (payload or {}).get("packs") or {}
            if not isinstance(target_packs, dict):
                return False
            path_value = target_packs.get(need)
            if not isinstance(path_value, str) or not Path(path_value).expanduser().resolve().is_file():
                return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure a workspace has the requested context layers")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--need", action="append", choices=["platform", "standards", "metadata", "code", "full"], required=True)
    parser.add_argument("--source-path", default=None)
    parser.add_argument("--source-kind", default="auto")
    parser.add_argument("--metadata-source", default=None)
    parser.add_argument("--hbk-base", default=None)
    parser.add_argument("--standards-dir", default=None)
    parser.add_argument("--platform", action="append", default=[])
    parser.add_argument("--base-config", action="append", default=[])
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    manifest_exists = _manifest_exists(workspace_root)
    needs = list(args.need or [])

    if manifest_exists:
        manifest = load_workspace_manifest(workspace_root)
        init_args = init_args_from_manifest(manifest)
        current_profile = str(manifest.get("profile") or "base")
        desired_profile = _desired_profile(current_profile, needs)
        source_path = str(init_args.get("source_path") or workspace_root)
        source_kind = str(init_args.get("source_kind") or "auto")
        metadata_source = args.metadata_source or init_args.get("metadata_source")
        hbk_base = args.hbk_base or init_args.get("hbk_base")
        standards_dir = args.standards_dir or init_args.get("standards_dir")
        platforms = list(args.platform or init_args.get("platforms") or [])
        base_configs = list(args.base_config or init_args.get("base_configs") or [])
        status_ok = _run_capture_ok(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "status_workspace.py"),
                "--workspace-root",
                str(workspace_root),
                "--strict",
            ]
        )
        if status_ok and _manifest_satisfies_needs(manifest, workspace_root, needs):
            print(
                json.dumps(
                    _public_payload({
                        "workspace_root": str(workspace_root),
                        "needs": needs,
                        "profile": current_profile,
                        "source_path": source_path,
                        "changed": False,
                    }),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    else:
        desired_profile = _desired_profile("base", needs)
        source_path = args.source_path or str(workspace_root)
        source_kind = args.source_kind or "auto"
        metadata_source = args.metadata_source
        hbk_base = args.hbk_base
        standards_dir = args.standards_dir
        platforms = list(args.platform or [])
        base_configs = list(args.base_config or [])

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "init_workspace.py"),
        "--workspace-root",
        str(workspace_root),
        "--source-path",
        str(source_path),
        "--source-kind",
        str(source_kind),
        "--profile",
        desired_profile,
    ]
    if metadata_source:
        cmd.extend(["--metadata-source", str(metadata_source)])
    if hbk_base:
        cmd.extend(["--hbk-base", str(hbk_base)])
    if "standards" in needs:
        cmd.append("--with-standards")
        if standards_dir:
            cmd.extend(["--standards-dir", str(standards_dir)])
        if "platform" not in needs and desired_profile == "base":
            cmd.append("--without-help")
    for version in platforms:
        cmd.extend(["--platform", str(version)])
    for base_config in base_configs:
        cmd.extend(["--base-config", str(base_config)])

    _run(cmd)
    result = {
        "workspace_root": str(workspace_root),
        "needs": needs,
        "profile": desired_profile,
        "source_path": source_path,
        "changed": True,
    }
    print(json.dumps(_public_payload(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
