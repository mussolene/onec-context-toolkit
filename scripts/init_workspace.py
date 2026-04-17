#!/usr/bin/env python3
"""Initialize a 1C workspace with source-driven local context packs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


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


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_root_info(source_path: Path) -> tuple[Path | None, str]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from onec_help.metadata_index import detect_config_source_kind, find_config_roots, is_config_source_root

    if is_config_source_root(source_path):
        return source_path, detect_config_source_kind(source_path)
    roots = find_config_roots(source_path)
    if roots:
        return roots[0], detect_config_source_kind(roots[0])
    return None, "unknown"


def _source_snapshot(config_root: Path | None) -> dict[str, object] | None:
    if config_root is None:
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


def init_workspace(args: argparse.Namespace) -> dict:
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    onec_root = workspace_root / ".onec"
    packs_dir = onec_root / "packs"
    manifests_dir = onec_root / "manifests"
    onec_root.mkdir(parents=True, exist_ok=True)
    packs_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(args.source_path or args.workspace_root).expanduser().resolve()
    config_root, detected_kind = _config_root_info(source_path)
    source_kind = args.source_kind if args.source_kind != "auto" else detected_kind

    manifest: dict[str, object] = {
        "format": "onec_workspace_manifest_v1",
        "created_at": _now_iso(),
        "workspace_root": str(workspace_root),
        "tool_repo": str(REPO_ROOT),
        "source_path": str(source_path),
        "source_kind": source_kind,
        "base_configs": list(args.base_config or []),
        "requested_platforms": list(args.platform or []),
        "packs": {},
        "optional_sources": {},
    }

    if args.metadata_source:
        manifest["optional_sources"]["metadata_export"] = str(
            Path(args.metadata_source).expanduser().resolve()
        )

    if config_root is not None:
        manifest["config_root"] = str(config_root)
        manifest["source_snapshot"] = _source_snapshot(config_root)
        metadata_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_local_kb.py"),
            "metadata",
            "--config-source",
            str(config_root),
            "--work-dir",
            str(onec_root / "work"),
            "--db-path",
            str(onec_root / "cache" / "metadata.kb.db"),
            "--out-zst",
            str(packs_dir / "metadata.kb.db.zst"),
            "--manifest",
            str(manifests_dir / "metadata.kb.manifest.json"),
        ]
        _run(metadata_args)
        manifest["packs"]["metadata"] = str(packs_dir / "metadata.kb.db.zst")

        code_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_code_pack.py"),
            "--source-dir",
            str(config_root),
            "--db-path",
            str(onec_root / "cache" / "code.pack.db"),
            "--out-zst",
            str(packs_dir / "code.pack.db.zst"),
            "--manifest",
            str(manifests_dir / "code.pack.manifest.json"),
        ]
        _run(code_args)
        manifest["packs"]["code"] = str(packs_dir / "code.pack.db.zst")

        if args.with_full_pack:
            full_args = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "build_config_pack.py"),
                "--source-dir",
                str(config_root),
                "--db-path",
                str(onec_root / "cache" / "config.dump.db"),
                "--out-zst",
                str(packs_dir / "config.dump.db.zst"),
                "--manifest",
                str(manifests_dir / "config.dump.manifest.json"),
            ]
            _run(full_args)
            manifest["packs"]["full"] = str(packs_dir / "config.dump.db.zst")
    elif args.metadata_source:
        metadata_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_local_kb.py"),
            "metadata",
            "--metadata-source",
            str(Path(args.metadata_source).expanduser().resolve()),
            "--work-dir",
            str(onec_root / "work"),
            "--db-path",
            str(onec_root / "cache" / "metadata.kb.db"),
            "--out-zst",
            str(packs_dir / "metadata.kb.db.zst"),
            "--manifest",
            str(manifests_dir / "metadata.kb.manifest.json"),
        ]
        _run(metadata_args)
        manifest["packs"]["metadata"] = str(packs_dir / "metadata.kb.db.zst")
    else:
        raise ValueError(
            "No ConfigDump source detected. Provide --source-path pointing to a Configuration.xml root or use --metadata-source as fallback."
        )

    hbk_base = _detect_hbk_base(args.hbk_base)
    if hbk_base is not None and args.with_help:
        help_args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_local_kb.py"),
            "help",
            "--hbk-base",
            str(hbk_base),
            "--work-dir",
            str(onec_root / "work"),
            "--db-path",
            str(onec_root / "cache" / "kb.db"),
            "--out-zst",
            str(packs_dir / "kb.db.zst"),
            "--manifest",
            str(manifests_dir / "kb.manifest.json"),
        ]
        if args.platform:
            for version in args.platform:
                help_args.extend(["--platform", version])
        _run(help_args)
        manifest["packs"]["platform"] = str(packs_dir / "kb.db.zst")
        manifest["optional_sources"]["hbk_base"] = str(hbk_base)

    manifest_path = onec_root / "workspace.manifest.json"
    _write_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a source-first 1C workspace context")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--source-path", default=".")
    parser.add_argument("--source-kind", default="auto", choices=["auto", "configdump", "extension", "metadata-export"])
    parser.add_argument("--base-config", action="append", default=[], help="Possible base configuration IDs/names for an extension workspace.")
    parser.add_argument("--metadata-source", default=None, help="Optional metadata XML export XML dir/file for fallback or verification.")
    parser.add_argument("--hbk-base", default=None, help="Optional HBK root; defaults to env or /opt/1cv8 when available.")
    parser.add_argument("--platform", action="append", default=[], help="Optional platform versions to include when building help.")
    parser.add_argument("--with-help", action="store_true", help="Build platform help pack when HBK is available.")
    parser.add_argument("--with-full-pack", action="store_true", help="Also build lossless ConfigDump pack.")
    args = parser.parse_args()
    manifest = init_workspace(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
