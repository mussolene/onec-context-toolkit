#!/usr/bin/env python3
"""Resolve workspace or bundle pack paths by role and target."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.workspace_manifest import (  # noqa: E402
    all_target_packs,
    list_targets,
    load_bundle_manifest,
    load_workspace_manifest,
    platform_pack,
    resolve_pack_path,
    resolve_target_pack,
)


def _load_manifest(args: argparse.Namespace) -> tuple[str, Path, dict]:
    if args.bundle_dir:
        bundle_root = Path(args.bundle_dir).expanduser().resolve()
        return "bundle", bundle_root, load_bundle_manifest(bundle_root)
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    return "workspace", workspace_root, load_workspace_manifest(workspace_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve exact pack paths from a workspace or bundle manifest")
    parser.add_argument("--workspace-root", default=".", help="Workspace root with .onec/workspace.manifest.json")
    parser.add_argument("--bundle-dir", default=None, help="Bundle root with bundle.manifest.json")
    parser.add_argument("--role", choices=["platform", "metadata", "code", "full"], default=None)
    parser.add_argument("--target", default=None, help="Source identity for target-bound roles")
    parser.add_argument("--all-targets", action="store_true", help="Return all target-bound pack paths for the selected role")
    parser.add_argument("--path-only", action="store_true", help="Print only the resolved path when one result is selected")
    args = parser.parse_args()

    manifest_kind, manifest_root, manifest = _load_manifest(args)
    targets_payload = []
    for item in list_targets(manifest):
        packs = item.get("packs") or {}
        if isinstance(packs, dict):
            item = {
                **item,
                "packs": {
                    name: str(resolve_pack_path(path_value, base_root=manifest_root))
                    for name, path_value in packs.items()
                    if isinstance(path_value, str)
                },
            }
        targets_payload.append(item)
    payload = {
        "kind": manifest_kind,
        "platform": (
            str(resolve_pack_path(platform_pack(manifest), base_root=manifest_root))
            if platform_pack(manifest)
            else None
        ),
        "targets": targets_payload,
    }

    if args.role is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.role == "platform":
        resolved = platform_pack(manifest)
        if not resolved:
            return 2
        resolved_path = str(resolve_pack_path(resolved, base_root=manifest_root))
        if args.path_only:
            print(resolved_path)
        else:
            print(json.dumps({"role": "platform", "path": resolved_path}, ensure_ascii=False, indent=2))
        return 0

    if args.all_targets:
        resolved_all = all_target_packs(manifest, role=args.role)
        if not resolved_all:
            return 2
        resolved_all = {
            target_name: str(resolve_pack_path(path_value, base_root=manifest_root))
            for target_name, path_value in resolved_all.items()
        }
        if args.path_only and len(resolved_all) == 1:
            print(next(iter(resolved_all.values())))
        else:
            print(json.dumps({"role": args.role, "targets": resolved_all}, ensure_ascii=False, indent=2))
        return 0

    resolved = resolve_target_pack(manifest, role=args.role, target=args.target)
    if not resolved:
        print(
            json.dumps(
                {
                    "role": args.role,
                    "target": args.target,
                    "error": "pack path is ambiguous or missing; provide --target or use --all-targets",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    resolved_path = str(resolve_pack_path(resolved, base_root=manifest_root))
    if args.path_only:
        print(resolved_path)
    else:
        print(json.dumps({"role": args.role, "target": args.target, "path": resolved_path}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
