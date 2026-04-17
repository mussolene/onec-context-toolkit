#!/usr/bin/env python3
"""Check workspace manifest drift against current source and built packs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _current_source_snapshot(config_root: Path | None) -> dict[str, object] | None:
    if config_root is None or not config_root.is_dir():
        return None
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from onec_help.metadata_index import get_config_source_info

    info = get_config_source_info(config_root)
    return {
        "source_root": str(info.source_root),
        "source_kind": info.source_kind,
        "config_name": info.config_name,
        "config_version": info.config_version,
        "configuration_xml": str(info.configuration_xml),
        "configuration_xml_mtime_ns": info.configuration_xml_mtime_ns,
    }


def _pack_manifest_path(pack_path: Path) -> Path:
    return pack_path.parent.parent / "manifests" / pack_path.name.replace(".db.zst", ".manifest.json")


def _pack_entry(name: str, pack_path: Path) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "path": str(pack_path),
        "exists": pack_path.is_file(),
    }
    manifest_path = _pack_manifest_path(pack_path)
    entry["manifest_path"] = str(manifest_path)
    entry["manifest_exists"] = manifest_path.is_file()
    if manifest_path.is_file():
        entry["manifest"] = _load_json(manifest_path)
    return entry


def collect_status(workspace_root: Path, requested_platforms: list[str] | None = None) -> dict[str, object]:
    workspace_root = workspace_root.expanduser().resolve()
    onec_root = workspace_root / ".onec"
    manifest_path = onec_root / "workspace.manifest.json"
    result: dict[str, object] = {
        "workspace_root": str(workspace_root),
        "onec_root": str(onec_root),
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.is_file(),
        "status": "missing",
        "issues": [],
        "packs": {},
    }
    if not manifest_path.is_file():
        result["issues"].append("workspace manifest is missing; run init")
        return result

    manifest = _load_json(manifest_path)
    result["manifest"] = manifest
    issues: list[str] = []
    pack_entries: dict[str, object] = {}

    config_root_value = manifest.get("config_root")
    config_root = Path(config_root_value) if isinstance(config_root_value, str) else None
    current_snapshot = _current_source_snapshot(config_root)
    recorded_snapshot = manifest.get("source_snapshot")
    result["current_source_snapshot"] = current_snapshot

    if recorded_snapshot != current_snapshot:
        issues.append("config source snapshot drifted; metadata/code/full packs should be rebuilt")

    packs = manifest.get("packs") or {}
    for name, path_value in packs.items():
        if not isinstance(path_value, str):
            issues.append(f"pack entry {name} has invalid path")
            continue
        pack_path = Path(path_value).expanduser().resolve()
        pack_entry = _pack_entry(name, pack_path)
        pack_entries[name] = pack_entry
        if not pack_entry["exists"]:
            issues.append(f"pack {name} is missing")
            continue
        if not pack_entry["manifest_exists"]:
            issues.append(f"manifest for pack {name} is missing")
            continue
        manifest_payload = pack_entry["manifest"]
        if name == "metadata" and current_snapshot is not None:
            versions_seen = (
                ((manifest_payload.get("stats") or {}).get("versions_seen") or {})
                if isinstance(manifest_payload, dict)
                else {}
            )
            current_version = str(current_snapshot.get("config_version") or "")
            if current_version and current_version not in versions_seen:
                issues.append("metadata pack does not contain current configuration version")
        if name in {"code", "full"} and current_snapshot is not None:
            source_dir = str(manifest_payload.get("source_dir") or "")
            if source_dir and source_dir != str(current_snapshot.get("source_root")):
                issues.append(f"{name} pack source root does not match current config root")
        if name == "platform":
            expected = requested_platforms or list(manifest.get("requested_platforms") or [])
            versions_seen = list((((manifest_payload.get("stats") or {}).get("versions_seen") or {})).keys())
            missing_platforms = [version for version in expected if version not in versions_seen]
            if missing_platforms:
                issues.append(
                    "platform help pack is missing requested versions: " + ", ".join(missing_platforms)
                )

    if str(manifest.get("source_kind") or "") == "extension" and not manifest.get("base_configs"):
        issues.append("extension workspace has no declared base_configs")

    result["packs"] = pack_entries
    result["issues"] = issues
    result["status"] = "ok" if not issues else "stale"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check workspace drift and pack health")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--platform", action="append", default=[], help="Expected platform version(s) for help pack verification.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when workspace is stale.")
    args = parser.parse_args()

    status = collect_status(Path(args.workspace_root), requested_platforms=list(args.platform or []))
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if args.strict and status["status"] != "ok":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
