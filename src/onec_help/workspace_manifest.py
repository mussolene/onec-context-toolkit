"""Helpers for workspace/bundle manifest inspection and pack resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def workspace_manifest_path(workspace_root: Path) -> Path:
    return workspace_root.expanduser().resolve() / ".onec" / "workspace.manifest.json"


def bundle_manifest_path(bundle_root: Path) -> Path:
    return bundle_root.expanduser().resolve() / "bundle.manifest.json"


def load_workspace_manifest(workspace_root: Path) -> dict[str, Any]:
    return load_json(workspace_manifest_path(workspace_root))


def load_bundle_manifest(bundle_root: Path) -> dict[str, Any]:
    return load_json(bundle_manifest_path(bundle_root))


def resolve_pack_path(value: str, *, base_root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_root / path).resolve()


def legacy_targets(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    packs = manifest.get("packs") or {}
    if not isinstance(packs, dict):
        packs = {}
    legacy_packs = {key: value for key, value in packs.items() if key in {"metadata", "code", "full"}}
    config_root = manifest.get("config_root")
    source_snapshot = manifest.get("source_snapshot")
    if not legacy_packs and not config_root and not source_snapshot:
        return {}
    source_identity = str(manifest.get("source_identity") or "legacy-target")
    return {
        source_identity: {
            "source_kind": manifest.get("source_kind"),
            "config_root": config_root,
            "source_snapshot": source_snapshot,
            "packs": legacy_packs,
        }
    }


def manifest_targets(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    targets = manifest.get("targets")
    if isinstance(targets, dict) and targets:
        return targets
    return legacy_targets(manifest)


def platform_pack(manifest: dict[str, Any]) -> str | None:
    packs = manifest.get("packs") or {}
    if isinstance(packs, dict):
        value = packs.get("platform")
        if isinstance(value, str):
            return value
    return None


def list_targets(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for target_name, target_payload in manifest_targets(manifest).items():
        payload = target_payload if isinstance(target_payload, dict) else {}
        snapshot = payload.get("source_snapshot") if isinstance(payload, dict) else None
        out.append(
            {
                "target": target_name,
                "source_kind": payload.get("source_kind"),
                "config_root": payload.get("config_root"),
                "config_name": (snapshot or {}).get("config_name") if isinstance(snapshot, dict) else None,
                "config_version": (snapshot or {}).get("config_version") if isinstance(snapshot, dict) else None,
                "packs": (payload.get("packs") or {}) if isinstance(payload, dict) else {},
            }
        )
    return out


def resolve_target_pack(manifest: dict[str, Any], *, role: str, target: str | None = None) -> str | None:
    targets = manifest_targets(manifest)
    if role in {"platform", "standards"}:
        if role == "platform":
            return platform_pack(manifest)
        packs = manifest.get("packs") or {}
        if isinstance(packs, dict):
            value = packs.get("standards")
            return value if isinstance(value, str) else None
        return None
    if not targets:
        return None
    if target is not None:
        payload = targets.get(target)
        if not isinstance(payload, dict):
            return None
        packs = payload.get("packs") or {}
        value = packs.get(role) if isinstance(packs, dict) else None
        return value if isinstance(value, str) else None
    if len(targets) == 1:
        only = next(iter(targets.values()))
        packs = only.get("packs") if isinstance(only, dict) else {}
        value = packs.get(role) if isinstance(packs, dict) else None
        return value if isinstance(value, str) else None
    return None


def all_target_packs(manifest: dict[str, Any], *, role: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for target_name, payload in manifest_targets(manifest).items():
        packs = payload.get("packs") if isinstance(payload, dict) else {}
        value = packs.get(role) if isinstance(packs, dict) else None
        if isinstance(value, str):
            out[target_name] = value
    return out


def init_args_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    optional_sources = manifest.get("optional_sources") or {}
    source_kind = str(manifest.get("source_kind") or "auto")
    if source_kind not in {"configdump", "extension", "metadata-export"}:
        source_kind = "auto"
    return {
        "source_path": manifest.get("source_path"),
        "source_kind": source_kind,
        "metadata_source": optional_sources.get("metadata_export"),
        "hbk_base": optional_sources.get("hbk_base"),
        "standards_dir": optional_sources.get("standards_dir"),
        "platforms": list(manifest.get("requested_platforms") or []),
        "base_configs": list(manifest.get("base_configs") or []),
        "profile": str(manifest.get("profile") or "base"),
    }
