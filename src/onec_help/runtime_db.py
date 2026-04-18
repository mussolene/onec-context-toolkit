"""Shared runtime helpers for opening local .db/.db.zst artifacts efficiently."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from onec_help.zstd_compat import decompress_path


REPO_ROOT = Path(__file__).resolve().parents[2]


def manifest_path_for_zst(path: Path) -> Path | None:
    if not path.name.endswith(".db.zst"):
        return None
    manifest_name = path.name.replace(".db.zst", ".manifest.json")
    manifest_path = path.with_name(manifest_name)
    return manifest_path if manifest_path.is_file() else None


def plain_db_candidates(path: Path) -> list[Path]:
    candidates: list[Path] = []
    if path.suffix == ".zst":
        candidates.append(path.with_suffix(""))
        manifest_path = manifest_path_for_zst(path)
        if manifest_path is not None:
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                db_path = payload.get("stats", {}).get("db_path")
                if isinstance(db_path, str) and db_path.strip():
                    db_candidate = Path(db_path)
                    if not db_candidate.is_absolute():
                        db_candidate = (REPO_ROOT / db_candidate).resolve()
                    candidates.append(db_candidate)
            except (OSError, ValueError, TypeError):
                pass
        if path.parent.name == "artifacts":
            candidates.append((REPO_ROOT / "build" / path.name.removesuffix(".zst")).resolve())
    return candidates


def cached_extract_path(path: Path, cache_name: str = "query_cache") -> Path:
    cache_dir = REPO_ROOT / "build" / cache_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    file_name = f"{path.name.removesuffix('.zst')}.{stat.st_size}.{stat.st_mtime_ns}.db"
    return cache_dir / file_name


def extract_once(path: Path, out_path: Path) -> None:
    fd, tmp = tempfile.mkstemp(prefix="onec_db_", suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp)
    tmp_path.unlink(missing_ok=True)
    try:
        decompress_path(path, tmp_path)
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def ensure_sqlite_db(path: Path, *, cache_name: str = "query_cache") -> tuple[Path, bool]:
    path = path.expanduser().resolve()
    if path.suffix != ".zst":
        return path, False
    for candidate in plain_db_candidates(path):
        if candidate.is_file():
            return candidate, False
    cache_path = cached_extract_path(path, cache_name=cache_name)
    if not cache_path.is_file():
        extract_once(path, cache_path)
    return cache_path, False
