#!/usr/bin/env python3
"""Smoke checks for local compact KB artifacts."""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "artifacts"


def _ensure_db(path: Path) -> tuple[Path, bool]:
    if path.suffix != ".zst":
        return path, False
    fd, tmp = tempfile.mkstemp(prefix="verify_kb_", suffix=".db")
    Path(tmp).unlink(missing_ok=True)
    subprocess.run(["zstd", "-q", "-d", "-f", str(path), "-o", tmp], check=True)
    return Path(tmp), True


def _check_query(path: Path, query: str) -> tuple[int, list[tuple[str, str, str]]]:
    db_path, temp = _ensure_db(path)
    try:
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
    finally:
        if temp:
            db_path.unlink(missing_ok=True)


def _blank_metadata_fields(path: Path) -> int:
    db_path, temp = _ensure_db(path)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        value = cur.execute(
            "SELECT count(*) FROM docs WHERE domain='metadata_fields' AND (name IS NULL OR name='')"
        ).fetchone()[0]
        con.close()
        return int(value)
    finally:
        if temp:
            db_path.unlink(missing_ok=True)


def _has_form_metadata(path: Path) -> bool:
    db_path, temp = _ensure_db(path)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        value = cur.execute(
            "SELECT 1 FROM docs WHERE domain='metadata_fields' AND topic_path LIKE '%.Forms.%' LIMIT 1"
        ).fetchone()
        con.close()
        return value is not None
    finally:
        if temp:
            db_path.unlink(missing_ok=True)


def _resolve_artifacts_dir(workspace_root: str | None, artifacts_dir: str | None) -> Path:
    if artifacts_dir:
        return Path(artifacts_dir).expanduser().resolve()
    if workspace_root:
        return Path(workspace_root).expanduser().resolve() / ".onec" / "packs"
    return ARTIFACTS


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke checks for local compact KB artifacts")
    parser.add_argument("--workspace-root", default=None, help="Workspace root with .onec/packs")
    parser.add_argument("--artifacts-dir", default=None, help="Explicit artifacts/packs directory")
    args = parser.parse_args()

    artifacts_dir = _resolve_artifacts_dir(args.workspace_root, args.artifacts_dir)
    checks = [
        (artifacts_dir / "metadata.kb.db.zst", "Document.РеализацияТоваровУслуг"),
        (artifacts_dir / "metadata.kb.db.zst", "Document.РеализацияТоваровУслуг.Товары.Номенклатура"),
    ]
    help_path = artifacts_dir / "kb.db.zst"
    if help_path.exists():
        checks = [
            (help_path, "HTTPСоединение.Получить"),
            *checks,
        ]
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
    metadata_path = artifacts_dir / "metadata.kb.db.zst"
    if metadata_path.exists():
        blank = _blank_metadata_fields(metadata_path)
        print(f"{metadata_path.name}: blank_metadata_fields={blank}")
        if blank != 0:
            failures += 1
        has_forms = _has_form_metadata(metadata_path)
        print(f"{metadata_path.name}: has_form_metadata={has_forms}")
        if not has_forms:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
