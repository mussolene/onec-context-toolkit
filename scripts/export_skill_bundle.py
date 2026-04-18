#!/usr/bin/env python3
"""Export a self-contained runtime skill bundle from a built workspace."""

from __future__ import annotations

import argparse
import json
import shutil
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_NAME = "onec-context-skill-bundle"
TEMPLATES_DIR = REPO_ROOT / "templates"
SUPPLEMENTAL_REFERENCES = (
    ("query_strategy_reference.md.tmpl", "references/query-strategy.md"),
    ("explain_object_reference.md.tmpl", "references/explain-object.md"),
    ("platform_fact_check_reference.md.tmpl", "references/platform-fact-check.md"),
)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _render_template(name: str, **values: str) -> str:
    template = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return template.format(**values)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_workspace_manifest(workspace_root: Path) -> dict:
    manifest_path = workspace_root / ".onec" / "workspace.manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"workspace manifest is missing: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _workspace_label(workspace_root: Path) -> str:
    return workspace_root.name or str(workspace_root)


def _sanitize_source_snapshot(snapshot: object) -> dict[str, object] | None:
    if not isinstance(snapshot, dict):
        return None
    out = {
        "source_kind": snapshot.get("source_kind"),
        "config_name": snapshot.get("config_name"),
        "config_version": snapshot.get("config_version"),
    }
    return {key: value for key, value in out.items() if value is not None}


def _bundle_source_summary(manifest: dict, workspace_root: Path) -> dict[str, object]:
    return {
        "workspace_label": _workspace_label(workspace_root),
        "source_kind": manifest.get("source_kind"),
        "source_layout": manifest.get("source_layout"),
        "profile": manifest.get("profile"),
        "requested_platforms": list(manifest.get("requested_platforms") or []),
        "base_configs": list(manifest.get("base_configs") or []),
    }


def _iter_manifest_packs(manifest: dict) -> list[tuple[str | None, str, Path]]:
    out: list[tuple[str | None, str, Path]] = []
    packs = manifest.get("packs") or {}
    if isinstance(packs, dict):
        for pack_name, pack_path_value in packs.items():
            if isinstance(pack_path_value, str):
                out.append((None, str(pack_name), Path(pack_path_value).expanduser().resolve()))
    targets = manifest.get("targets") or {}
    if isinstance(targets, dict):
        for target_name, target_payload in targets.items():
            target_packs = (target_payload or {}).get("packs") or {}
            if not isinstance(target_packs, dict):
                continue
            for pack_name, pack_path_value in target_packs.items():
                if isinstance(pack_path_value, str):
                    out.append((str(target_name), str(pack_name), Path(pack_path_value).expanduser().resolve()))
    return out


def export_bundle(workspace_root: Path, output_dir: Path, bundle_name: str) -> Path:
    workspace_root = workspace_root.expanduser().resolve()
    manifest = _load_workspace_manifest(workspace_root)
    bundle_root = output_dir / bundle_name
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    runtime_files = [
        (REPO_ROOT / "skill" / "SKILL.md", bundle_root / "SKILL.md"),
        (REPO_ROOT / "docs" / "1c-platform-cli.md", bundle_root / "docs" / "1c-platform-cli.md"),
        (REPO_ROOT / "tools" / "local_kb_query.py", bundle_root / "tools" / "local_kb_query.py"),
        (REPO_ROOT / "tools" / "verify_local_kb.py", bundle_root / "tools" / "verify_local_kb.py"),
        (REPO_ROOT / "tools" / "benchmark_local_kb.py", bundle_root / "tools" / "benchmark_local_kb.py"),
        (REPO_ROOT / "scripts" / "resolve_packs.py", bundle_root / "tools" / "resolve_packs.py"),
        (REPO_ROOT / "tools" / "query_config_pack.py", bundle_root / "tools" / "query_config_pack.py"),
        (REPO_ROOT / "tools" / "query_code_pack.py", bundle_root / "tools" / "query_code_pack.py"),
        (REPO_ROOT / "src" / "onec_help" / "__init__.py", bundle_root / "src" / "onec_help" / "__init__.py"),
        (REPO_ROOT / "src" / "onec_help" / "runtime_db.py", bundle_root / "src" / "onec_help" / "runtime_db.py"),
        (REPO_ROOT / "src" / "onec_help" / "workspace_manifest.py", bundle_root / "src" / "onec_help" / "workspace_manifest.py"),
        (REPO_ROOT / "src" / "onec_help" / "zstd_compat.py", bundle_root / "src" / "onec_help" / "zstd_compat.py"),
        (REPO_ROOT / "tools" / "1c" / "external data processor file", bundle_root / "tools" / "1c" / "external data processor file"),
        (REPO_ROOT / "tools" / "1c" / "external data processor root XML", bundle_root / "tools" / "1c" / "external data processor root XML"),
        (REPO_ROOT / "tools" / "1c" / "build_external_data_processor.sh", bundle_root / "tools" / "1c" / "build_external_data_processor.sh"),
    ]
    for src, dst in runtime_files:
        if not src.is_file():
            raise FileNotFoundError(f"required bundle file is missing: {src}")
        _copy(src, dst)
    for template_name, rel_dst in SUPPLEMENTAL_REFERENCES:
        _write(bundle_root / rel_dst, _render_template(template_name))

    copied_files: list[str] = []
    copied_packs: dict[str, str] = {}
    copied_targets: dict[str, dict[str, object]] = {}
    targets = manifest.get("targets") or {}
    for target_name, pack_name, pack_path in _iter_manifest_packs(manifest):
        if not pack_path.is_file():
            raise FileNotFoundError(f"workspace pack is missing: {pack_path}")
        pack_manifest = pack_path.parent.parent / "manifests" / pack_path.name.replace(".db.zst", ".manifest.json")
        if not pack_manifest.is_file():
            raise FileNotFoundError(f"workspace pack manifest is missing: {pack_manifest}")
        pack_dst = bundle_root / "artifacts" / pack_path.name
        manifest_dst = bundle_root / "artifacts" / pack_manifest.name
        _copy(pack_path, pack_dst)
        _copy(pack_manifest, manifest_dst)
        rel_pack = str(pack_dst.relative_to(bundle_root)).replace("\\", "/")
        if target_name is None:
            copied_packs[str(pack_name)] = rel_pack
        else:
            original_target = targets.get(target_name) if isinstance(targets, dict) else {}
            sanitized_target = copied_targets.setdefault(
                str(target_name),
                {
                    "source_kind": (original_target or {}).get("source_kind") if isinstance(original_target, dict) else None,
                    "source_snapshot": _sanitize_source_snapshot((original_target or {}).get("source_snapshot")),
                    "packs": {},
                },
            )
            target_packs = sanitized_target["packs"]
            assert isinstance(target_packs, dict)
            target_packs[str(pack_name)] = rel_pack
        copied_files.extend(
            [
                rel_pack,
                str(manifest_dst.relative_to(bundle_root)).replace("\\", "/"),
            ]
        )

    bundle_manifest = {
        "format": "onec_skill_bundle_v1",
        "name": bundle_name,
        "source_workspace": _bundle_source_summary(manifest, workspace_root),
        "packs": copied_packs,
        "targets": copied_targets,
        "files": copied_files,
    }
    _write(bundle_root / "bundle.manifest.json", json.dumps(bundle_manifest, ensure_ascii=False, indent=2))
    _write(
        bundle_root / "README.md",
        _render_template(
            "bundle_readme.md.tmpl",
            workspace_label=_workspace_label(workspace_root),
            source_kind=str(manifest.get("source_kind") or "unknown"),
        ),
    )
    return bundle_root


def create_archive(bundle_root: Path) -> Path:
    archive_path = bundle_root.with_suffix(".tar.gz")
    if archive_path.exists():
        archive_path.unlink()
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(bundle_root, arcname=bundle_root.name)
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export runtime skill bundle from a workspace .onec")
    parser.add_argument("--workspace-root", default=".", help="Workspace root that already contains .onec/")
    parser.add_argument("--output-dir", default="dist", help="Directory for exported bundle")
    parser.add_argument("--name", default=DEFAULT_BUNDLE_NAME, help="Bundle folder name")
    parser.add_argument("--archive", action="store_true", help="Also create .tar.gz archive")
    args = parser.parse_args()

    output_dir = (REPO_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_root = export_bundle(Path(args.workspace_root), output_dir, args.name)
    print(f"bundle_dir: {bundle_root}")
    if args.archive:
        archive_path = create_archive(bundle_root)
        print(f"bundle_archive: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
