#!/usr/bin/env python3
"""Initialize a 1C workspace with source-driven local context packs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _detect_hbk_base(explicit: str | None) -> Path | None:
    candidates = [
        explicit,
        os.environ.get("ONEC_HBK_BASE"),
        "/opt/1cv8",
    ]
    for value in candidates:
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            return path
    return None


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug_part(value: str) -> str:
    text = " ".join((value or "").strip().split()).lower()
    text = re.sub(r"[^\w.-]+", "-", text, flags=re.UNICODE)
    text = text.strip("._-")
    return text or "unnamed"


def _platform_pack_stem(requested_versions: list[str]) -> str:
    if not requested_versions:
        return "platform.all"
    uniq = sorted({_slug_part(version) for version in requested_versions if str(version).strip()})
    return "platform." + "+".join(uniq)


def _pack_paths(onec_root: Path, *, source_stem: str, requested_platforms: list[str]) -> dict[str, dict[str, Path]]:
    cache_dir = onec_root / "cache"
    packs_dir = onec_root / "packs"
    manifests_dir = onec_root / "manifests"
    platform_stem = _platform_pack_stem(requested_platforms)
    return {
        "metadata": {
            "db": cache_dir / f"{source_stem}.metadata.kb.db",
            "zst": packs_dir / f"{source_stem}.metadata.kb.db.zst",
            "manifest": manifests_dir / f"{source_stem}.metadata.kb.manifest.json",
        },
        "code": {
            "db": cache_dir / f"{source_stem}.code.pack.db",
            "zst": packs_dir / f"{source_stem}.code.pack.db.zst",
            "manifest": manifests_dir / f"{source_stem}.code.pack.manifest.json",
        },
        "full": {
            "db": cache_dir / f"{source_stem}.config.dump.db",
            "zst": packs_dir / f"{source_stem}.config.dump.db.zst",
            "manifest": manifests_dir / f"{source_stem}.config.dump.manifest.json",
        },
        "platform": {
            "db": cache_dir / f"{platform_stem}.kb.db",
            "zst": packs_dir / f"{platform_stem}.kb.db.zst",
            "manifest": manifests_dir / f"{platform_stem}.kb.manifest.json",
        },
    }


def _fallback_source_stem(source_path: Path, metadata_source: str | None) -> str:
    if metadata_source:
        source = Path(metadata_source).expanduser().resolve()
        return f"metadata-fallback.{_slug_part(source.stem)}"
    return f"workspace.{_slug_part(source_path.name or 'root')}"


def _config_source_infos(source_path: Path) -> list[Any]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from onec_help.metadata_index import list_config_source_infos

    return list_config_source_infos(source_path)


def _source_snapshot_from_info(info: Any) -> dict[str, object]:
    return {
        "source_root": str(info.source_root),
        "source_kind": info.source_kind,
        "config_name": info.config_name,
        "config_version": info.config_version,
        "configuration_xml": str(info.configuration_xml),
        "configuration_xml_mtime_ns": info.configuration_xml_mtime_ns,
    }


def _target_identities(config_infos: list[Any]) -> list[tuple[Any, str]]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from onec_help.metadata_index import source_identity_stem

    base_counts: dict[str, int] = {}
    for info in config_infos:
        base = source_identity_stem(info)
        base_counts[base] = base_counts.get(base, 0) + 1

    used: set[str] = set()
    out: list[tuple[Any, str]] = []
    for idx, info in enumerate(config_infos, start=1):
        base = source_identity_stem(info)
        identity = base
        if base_counts[base] > 1:
            identity = f"{base}.{_slug_part(Path(info.source_root).name)}"
            if identity in used:
                identity = f"{identity}.{idx}"
        used.add(identity)
        out.append((info, identity))
    return out


def _build_flags(args: argparse.Namespace) -> tuple[bool, bool, bool, bool]:
    build_help = not bool(args.without_help)
    build_metadata = bool(args.with_metadata)
    build_code = bool(args.with_code)
    build_full = bool(args.with_full_pack)

    if args.profile == "base":
        build_help = True if not args.without_help else False
    elif args.profile == "metadata":
        build_help = True if not args.without_help else False
        build_metadata = True
    elif args.profile == "dev":
        build_help = True if not args.without_help else False
        build_metadata = True
        build_code = True
    elif args.profile == "full":
        build_help = True if not args.without_help else False
        build_metadata = True
        build_code = True
        build_full = True

    if build_code or build_full:
        build_metadata = True

    return build_help, build_metadata, build_code, build_full


def init_workspace(args: argparse.Namespace) -> dict[str, Any]:
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    onec_root = workspace_root / ".onec"
    (onec_root / "packs").mkdir(parents=True, exist_ok=True)
    (onec_root / "manifests").mkdir(parents=True, exist_ok=True)
    (onec_root / "cache").mkdir(parents=True, exist_ok=True)
    (onec_root / "work").mkdir(parents=True, exist_ok=True)

    source_path = Path(args.source_path or args.workspace_root).expanduser().resolve()
    config_infos = _config_source_infos(source_path)
    source_layout = "single-root" if len(config_infos) == 1 else "multi-root" if config_infos else "no-config-root"
    detected_kind = config_infos[0].source_kind if len(config_infos) == 1 else "multi-root" if config_infos else "unknown"
    source_kind = args.source_kind if args.source_kind != "auto" else detected_kind
    build_help, build_metadata, build_code, build_full = _build_flags(args)

    manifest: dict[str, Any] = {
        "format": "onec_workspace_manifest_v2",
        "created_at": _now_iso(),
        "workspace_root": str(workspace_root),
        "tool_repo": str(REPO_ROOT),
        "source_path": str(source_path),
        "source_kind": str(source_kind),
        "source_layout": source_layout,
        "profile": args.profile,
        "base_configs": list(args.base_config or []),
        "requested_platforms": list(args.platform or []),
        "packs": {},
        "targets": {},
        "optional_sources": {},
    }

    if args.metadata_source:
        manifest["optional_sources"]["metadata_export"] = str(
            Path(args.metadata_source).expanduser().resolve()
        )

    if config_infos:
        manifest["source_identities"] = []
        for info, source_identity in _target_identities(config_infos):
            snapshot = _source_snapshot_from_info(info)
            pack_paths = _pack_paths(
                onec_root,
                source_stem=source_identity,
                requested_platforms=list(args.platform or []),
            )
            target_manifest: dict[str, Any] = {
                "source_kind": info.source_kind,
                "config_root": str(info.source_root),
                "source_snapshot": snapshot,
                "packs": {},
            }
            manifest["targets"][source_identity] = target_manifest
            manifest["source_identities"].append(source_identity)

            if build_metadata:
                metadata_args = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "build_local_kb.py"),
                    "metadata",
                    "--config-source",
                    str(info.source_root),
                    "--work-dir",
                    str(onec_root / "work" / source_identity),
                    "--db-path",
                    str(pack_paths["metadata"]["db"]),
                    "--out-zst",
                    str(pack_paths["metadata"]["zst"]),
                    "--manifest",
                    str(pack_paths["metadata"]["manifest"]),
                ]
                _run(metadata_args)
                target_manifest["packs"]["metadata"] = str(pack_paths["metadata"]["zst"])

                if build_code:
                    code_args = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "build_code_pack.py"),
                        "--source-dir",
                        str(info.source_root),
                        "--db-path",
                        str(pack_paths["code"]["db"]),
                        "--out-zst",
                        str(pack_paths["code"]["zst"]),
                        "--manifest",
                        str(pack_paths["code"]["manifest"]),
                    ]
                    _run(code_args)
                    target_manifest["packs"]["code"] = str(pack_paths["code"]["zst"])

                if build_full:
                    full_args = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "build_config_pack.py"),
                        "--source-dir",
                        str(info.source_root),
                        "--db-path",
                        str(pack_paths["full"]["db"]),
                        "--out-zst",
                        str(pack_paths["full"]["zst"]),
                        "--manifest",
                        str(pack_paths["full"]["manifest"]),
                    ]
                    _run(full_args)
                    target_manifest["packs"]["full"] = str(pack_paths["full"]["zst"])
    elif build_metadata:
        if not args.metadata_source:
            raise ValueError(
                "No ConfigDump source detected. Provide --source-path pointing to a Configuration.xml root or use --metadata-source as fallback."
            )
        source_identity = _fallback_source_stem(source_path, args.metadata_source)
        pack_paths = _pack_paths(
            onec_root,
            source_stem=source_identity,
            requested_platforms=list(args.platform or []),
        )
        metadata_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_local_kb.py"),
            "metadata",
            "--metadata-source",
            str(Path(args.metadata_source).expanduser().resolve()),
            "--work-dir",
            str(onec_root / "work" / source_identity),
            "--db-path",
            str(pack_paths["metadata"]["db"]),
            "--out-zst",
            str(pack_paths["metadata"]["zst"]),
            "--manifest",
            str(pack_paths["metadata"]["manifest"]),
        ]
        _run(metadata_args)
        manifest["targets"][source_identity] = {
            "source_kind": "metadata-export",
            "config_root": None,
            "source_snapshot": None,
            "packs": {
                "metadata": str(pack_paths["metadata"]["zst"]),
            },
        }

    hbk_base = _detect_hbk_base(args.hbk_base)
    if build_help and hbk_base is None:
        raise ValueError(
            "Platform help is mandatory for the selected profile. Provide --hbk-base, set ONEC_HBK_BASE, or use --without-help only for an explicit nonstandard flow."
        )
    if hbk_base is not None and build_help:
        fallback_stem = (
            manifest.get("source_identities", [None])[0]
            if manifest.get("source_identities")
            else _fallback_source_stem(source_path, args.metadata_source)
        )
        pack_paths = _pack_paths(
            onec_root,
            source_stem=str(fallback_stem),
            requested_platforms=list(args.platform or []),
        )
        help_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_local_kb.py"),
            "help",
            "--hbk-base",
            str(hbk_base),
            "--work-dir",
            str(onec_root / "work"),
            "--db-path",
            str(pack_paths["platform"]["db"]),
            "--out-zst",
            str(pack_paths["platform"]["zst"]),
            "--manifest",
            str(pack_paths["platform"]["manifest"]),
        ]
        for version in args.platform or []:
            help_args.extend(["--platform", version])
        _run(help_args)
        manifest["packs"]["platform"] = str(pack_paths["platform"]["zst"])
        manifest["optional_sources"]["hbk_base"] = str(hbk_base)

    manifest_path = onec_root / "workspace.manifest.json"
    _write_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a source-first 1C workspace context")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--source-path", default=".")
    parser.add_argument("--source-kind", default="auto", choices=["auto", "configdump", "extension", "metadata-export"])
    parser.add_argument(
        "--profile",
        default="base",
        choices=["base", "metadata", "dev", "full"],
        help="base=help only, metadata=help+metadata, dev=help+metadata+code, full=help+metadata+code+full-pack",
    )
    parser.add_argument("--base-config", action="append", default=[], help="Possible base configuration IDs/names for an extension workspace.")
    parser.add_argument("--metadata-source", default=None, help="Optional metadata XML export XML dir/file for fallback or verification.")
    parser.add_argument("--hbk-base", default=None, help="Optional HBK root; may point to a platform root, exact version dir, or version/bin dir. Defaults to env or /opt/1cv8 when available.")
    parser.add_argument("--platform", action="append", default=[], help="Optional platform versions to include when building help.")
    parser.add_argument("--without-help", action="store_true", help="Disable platform help even though it is part of the default base profile.")
    parser.add_argument("--with-metadata", action="store_true", help="Also build metadata on top of the selected profile.")
    parser.add_argument("--with-code", action="store_true", help="Also build code.pack on top of the selected profile.")
    parser.add_argument("--with-full-pack", action="store_true", help="Also build lossless ConfigDump pack.")
    args = parser.parse_args()
    manifest = init_workspace(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
