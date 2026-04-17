#!/usr/bin/env python3
"""Smoke checks for local compact KB artifacts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "artifacts"
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.runtime_db import ensure_sqlite_db  # noqa: E402
from onec_help.workspace_manifest import load_workspace_manifest, manifest_targets, platform_pack  # noqa: E402


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_query(path: Path, query: str) -> tuple[int, list[tuple[str, str, str]]]:
    db_path, _temp = ensure_sqlite_db(path, cache_name="verify_cache")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT domain, name, topic_path
        FROM docs
        WHERE lower(name)=lower(?) OR lower(topic_path)=lower(?)
        LIMIT 5
        """,
        (query, query),
    ).fetchall()
    con.close()
    return len(rows), rows


def _blank_metadata_fields(path: Path) -> int:
    db_path, _temp = ensure_sqlite_db(path, cache_name="verify_cache")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    value = cur.execute(
        "SELECT count(*) FROM docs WHERE domain='metadata_fields' AND (name IS NULL OR name='')"
    ).fetchone()[0]
    con.close()
    return int(value)


def _has_form_metadata(path: Path) -> bool:
    db_path, _temp = ensure_sqlite_db(path, cache_name="verify_cache")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    value = cur.execute(
        "SELECT 1 FROM docs WHERE domain='metadata_fields' AND topic_path LIKE '%.Forms.%' LIMIT 1"
    ).fetchone()
    con.close()
    return value is not None


def _resolve_artifacts_dir(workspace_root: str | None, artifacts_dir: str | None) -> Path:
    if artifacts_dir:
        return Path(artifacts_dir).expanduser().resolve()
    if workspace_root:
        return Path(workspace_root).expanduser().resolve() / ".onec" / "packs"
    return ARTIFACTS


def _manifest_pack_map(artifacts_dir: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {"platform": [], "metadata": [], "code": [], "full": []}
    kind_map = {
        "help": "platform",
        "metadata": "metadata",
        "code_pack": "code",
        "config_pack": "full",
    }
    for manifest_path in sorted(artifacts_dir.glob("*.manifest.json")):
        try:
            payload = _load_json(manifest_path)
        except Exception:
            continue
        kind = kind_map.get(str(payload.get("kind") or "").strip())
        if not kind:
            continue
        pack_path = artifacts_dir / manifest_path.name.replace(".manifest.json", ".db.zst")
        if not pack_path.is_file():
            continue
        result[kind].append(pack_path)
    return result


def _dedupe(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _resolve_pack_paths(workspace_root: str | None, artifacts_dir: str | None) -> dict[str, list[Path]]:
    base_dir = _resolve_artifacts_dir(workspace_root, artifacts_dir)
    fallback = {
        "metadata": [base_dir / "metadata.kb.db.zst"],
        "platform": [base_dir / "kb.db.zst"],
        "code": [base_dir / "code.pack.db.zst"],
        "full": [base_dir / "config.dump.db.zst"],
    }
    if workspace_root:
        manifest_path = Path(workspace_root).expanduser().resolve() / ".onec" / "workspace.manifest.json"
        if manifest_path.is_file():
            payload = load_workspace_manifest(Path(workspace_root))
            resolved = {"platform": [], "metadata": [], "code": [], "full": []}
            platform = platform_pack(payload)
            if platform:
                resolved["platform"].append(Path(platform).expanduser().resolve())
            for target in manifest_targets(payload).values():
                target_packs = (target or {}).get("packs") or {}
                if not isinstance(target_packs, dict):
                    continue
                for kind in ("metadata", "code", "full"):
                    value = target_packs.get(kind)
                    if isinstance(value, str):
                        resolved[kind].append(Path(value).expanduser().resolve())
            if any(resolved.values()):
                return {
                    kind: _dedupe(paths) if paths else fallback[kind]
                    for kind, paths in resolved.items()
                }
    by_kind = _manifest_pack_map(base_dir)
    return {
        kind: _dedupe(paths) if paths else fallback[kind]
        for kind, paths in by_kind.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke checks for local compact KB artifacts")
    parser.add_argument("--workspace-root", default=None, help="Workspace root with .onec/packs")
    parser.add_argument("--artifacts-dir", default=None, help="Explicit artifacts/packs directory")
    args = parser.parse_args()

    pack_paths = _resolve_pack_paths(args.workspace_root, args.artifacts_dir)
    checks: list[tuple[Path, str]] = []
    help_paths = [path for path in pack_paths["platform"] if path.exists()]
    if help_paths:
        checks = [
            (help_paths[0], "HTTPСоединение.Получить"),
            *checks,
        ]
    metadata_paths = [path for path in pack_paths["metadata"] if path.exists()]
    failures = 0
    for path, query in checks:
        if not path.exists():
            print(f"missing: {path}")
            failures += 1
            continue
        count, rows = _check_query(path, query)
        print(f"{path.name}: query={query!r} hits={count}")
        for domain, name, topic_path in rows:
            print(f"  - [{domain}] {name} -> {topic_path}")
        if count == 0:
            failures += 1
    for query in (
        "Document.РеализацияТоваровУслуг",
        "Document.РеализацияТоваровУслуг.Товары.Номенклатура",
    ):
        if metadata_paths:
            total_hits = 0
            for path in metadata_paths:
                count, rows = _check_query(path, query)
                if count == 0:
                    continue
                total_hits += count
                print(f"{path.name}: query={query!r} hits={count}")
                for domain, name, topic_path in rows:
                    print(f"  - [{domain}] {name} -> {topic_path}")
            if total_hits == 0:
                failures += 1
    if metadata_paths:
        for metadata_path in metadata_paths:
            blank = _blank_metadata_fields(metadata_path)
            print(f"{metadata_path.name}: blank_metadata_fields={blank}")
            if blank != 0:
                failures += 1
            has_forms = _has_form_metadata(metadata_path)
            print(f"{metadata_path.name}: has_form_metadata={has_forms}")
            if not has_forms:
                failures += 1
    else:
        print("metadata pack is absent; skipping metadata smoke checks")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
