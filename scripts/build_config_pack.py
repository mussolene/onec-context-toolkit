#!/usr/bin/env python3
"""Pack a 1C ConfigDump folder into a compact lossless SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path

import compression.zstd as zstd


REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {
    ".bsl",
    ".css",
    ".html",
    ".htm",
    ".js",
    ".json",
    ".md",
    ".mdo",
    ".sql",
    ".st",
    ".svg",
    ".txt",
    ".xml",
    ".xsd",
    ".xsl",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _path_for_manifest(path: Path | str) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _guess_text_encoding(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            data.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return None


def _text_excerpt(data: bytes, path: Path, max_chars: int) -> tuple[str, str | None, str]:
    content_kind = "binary"
    if path.suffix.lower() in TEXT_EXTENSIONS and b"\x00" not in data:
        encoding = _guess_text_encoding(data)
        if encoding is not None:
            text = data.decode(encoding, errors="replace")
            excerpt = " ".join(text.split())
            if len(excerpt) > max_chars:
                excerpt = excerpt[: max_chars - 1].rstrip() + "…"
            return excerpt, encoding, "text"
    return "", None, content_kind


def _object_hint(rel_path: Path, entry_type: str) -> tuple[str, str]:
    parts = rel_path.parts
    if not parts:
        return "", ""
    if len(parts) == 1:
        part = parts[0]
        if entry_type == "file":
            return "root_file", Path(part).stem
        return "root_dir", part
    object_type = parts[0]
    object_name = Path(parts[1]).stem if entry_type == "file" and len(parts) == 2 else parts[1]
    return object_type, object_name


def _iter_entries(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        dir_path = Path(dirpath)
        if dir_path != root:
            yield "dir", dir_path
        for filename in filenames:
            yield "file", dir_path / filename


def _create_pack_db(db_path: Path) -> sqlite3.Connection:
    _ensure_parent(db_path)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.execute("PRAGMA cache_size=-80000")
    cur.execute("PRAGMA page_size=65536")
    cur.execute(
        """
        CREATE TABLE pack_meta(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE entries(
            id INTEGER PRIMARY KEY,
            rel_path TEXT NOT NULL UNIQUE,
            parent_path TEXT,
            entry_type TEXT NOT NULL,
            name TEXT NOT NULL,
            ext TEXT,
            size_bytes INTEGER,
            mode INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT,
            compression TEXT,
            blob_size INTEGER,
            content_kind TEXT,
            text_encoding TEXT,
            object_type TEXT,
            object_name TEXT,
            text_excerpt TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE file_blobs(
            entry_id INTEGER PRIMARY KEY,
            data BLOB NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE entries_fts
        USING fts5(rel_path, object_type, object_name, text_excerpt, content='entries', content_rowid='id')
        """
    )
    con.commit()
    return con


def _finalize_pack_db(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO entries_fts(rowid, rel_path, object_type, object_name, text_excerpt)
        SELECT id, rel_path, object_type, object_name, text_excerpt FROM entries
        """
    )
    cur.execute("CREATE INDEX idx_entries_type ON entries(entry_type)")
    cur.execute("CREATE INDEX idx_entries_parent_path ON entries(parent_path)")
    cur.execute("CREATE INDEX idx_entries_object ON entries(object_type, object_name)")
    cur.execute("CREATE INDEX idx_entries_sha256 ON entries(sha256)")
    con.commit()


def _pack_zstd(src_db: Path, out_zst: Path) -> int:
    _ensure_parent(out_zst)
    subprocess.run(["zstd", "-q", "-19", "-f", str(src_db), "-o", str(out_zst)], check=True)
    return out_zst.stat().st_size


def _write_manifest(path: Path, payload: dict) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _choose_sample_paths(paths: list[str], count: int) -> list[str]:
    if count <= 0 or not paths:
        return []
    if len(paths) <= count:
        return paths
    chosen: list[str] = []
    step = max(1, len(paths) // count)
    idx = 0
    while idx < len(paths) and len(chosen) < count - 1:
        chosen.append(paths[idx])
        idx += step
    chosen.append(paths[-1])
    out: list[str] = []
    seen: set[str] = set()
    for item in chosen:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out[:count]


def _verify_samples(root: Path, db_path: Path, rel_paths: list[str]) -> dict:
    if not rel_paths:
        return {"checked": 0, "mismatches": []}

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    mismatches: list[str] = []
    for rel_path in rel_paths:
        source_path = root / rel_path
        row = cur.execute(
            """
            SELECT e.sha256, e.compression, b.data
            FROM entries e
            JOIN file_blobs b ON b.entry_id = e.id
            WHERE e.rel_path = ?
            """,
            (rel_path,),
        ).fetchone()
        if row is None:
            mismatches.append(f"{rel_path}:missing-in-db")
            continue
        expected_sha, compression, blob = row
        data = zstd.decompress(blob) if compression == "zstd" else blob
        if _sha256_bytes(data) != expected_sha:
            mismatches.append(f"{rel_path}:blob-sha-mismatch")
            continue
        if not source_path.is_file():
            mismatches.append(f"{rel_path}:missing-source")
            continue
        if _sha256_bytes(source_path.read_bytes()) != expected_sha:
            mismatches.append(f"{rel_path}:source-sha-mismatch")
    con.close()
    return {"checked": len(rel_paths), "mismatches": mismatches}


def build_pack(
    *,
    source_dir: Path,
    db_path: Path,
    out_zst: Path,
    manifest_path: Path,
    keep_db: bool,
    excerpt_chars: int,
    zstd_level: int,
    sample_verify: int,
    quiet: bool,
) -> dict:
    started_at = time.perf_counter()
    con = _create_pack_db(db_path)
    cur = con.cursor()

    file_paths: list[str] = []
    file_count = 0
    dir_count = 0
    total_source_bytes = 0
    total_blob_bytes = 0
    ext_counts: Counter[str] = Counter()
    object_type_counts: Counter[str] = Counter()
    content_kind_counts: Counter[str] = Counter()
    batch_count = 0

    cur.executemany(
        "INSERT INTO pack_meta(key, value) VALUES(?, ?)",
        [
            ("format", "1c-config-pack/v1"),
            ("source_root", str(source_dir)),
            ("created_at", _now_iso()),
        ],
    )

    for entry_type, path in _iter_entries(source_dir):
        rel_path = path.relative_to(source_dir)
        rel_str = rel_path.as_posix()
        parent_path = rel_path.parent.as_posix() if rel_path.parent != Path(".") else None
        stat = path.stat()
        object_type, object_name = _object_hint(rel_path, entry_type)
        object_type_counts[object_type or "<none>"] += 1
        if entry_type == "dir":
            dir_count += 1
            cur.execute(
                """
                INSERT INTO entries(
                    rel_path, parent_path, entry_type, name, ext, size_bytes, mode, mtime_ns,
                    sha256, compression, blob_size, content_kind, text_encoding,
                    object_type, object_name, text_excerpt
                ) VALUES(?, ?, 'dir', ?, '', NULL, ?, ?, NULL, NULL, NULL, 'dir', NULL, ?, ?, '')
                """,
                (rel_str, parent_path, path.name, stat.st_mode, stat.st_mtime_ns, object_type, object_name),
            )
        else:
            data = path.read_bytes()
            sha256 = _sha256_bytes(data)
            excerpt, encoding, content_kind = _text_excerpt(data, path, excerpt_chars)
            blob = zstd.compress(data, level=zstd_level)
            ext = path.suffix.lower()
            entry_id = cur.execute(
                """
                INSERT INTO entries(
                    rel_path, parent_path, entry_type, name, ext, size_bytes, mode, mtime_ns,
                    sha256, compression, blob_size, content_kind, text_encoding,
                    object_type, object_name, text_excerpt
                ) VALUES(?, ?, 'file', ?, ?, ?, ?, ?, ?, 'zstd', ?, ?, ?, ?, ?, ?)
                """,
                (
                    rel_str,
                    parent_path,
                    path.name,
                    ext,
                    len(data),
                    stat.st_mode,
                    stat.st_mtime_ns,
                    sha256,
                    len(blob),
                    content_kind,
                    encoding,
                    object_type,
                    object_name,
                    excerpt,
                ),
            ).lastrowid
            cur.execute(
                "INSERT INTO file_blobs(entry_id, data) VALUES(?, ?)",
                (entry_id, sqlite3.Binary(blob)),
            )
            file_paths.append(rel_str)
            file_count += 1
            total_source_bytes += len(data)
            total_blob_bytes += len(blob)
            ext_counts[ext or "<none>"] += 1
            content_kind_counts[content_kind] += 1

        batch_count += 1
        if batch_count >= 250:
            con.commit()
            if not quiet:
                print(f"[config-pack] entries={file_count + dir_count} files={file_count} dirs={dir_count}")
            batch_count = 0

    con.commit()
    _finalize_pack_db(con)
    con.close()

    sample_paths = _choose_sample_paths(file_paths, sample_verify)
    verification = _verify_samples(source_dir, db_path, sample_paths)
    if verification["mismatches"]:
        raise RuntimeError("Config pack sample verification failed: " + ", ".join(verification["mismatches"]))

    db_bytes = db_path.stat().st_size
    zst_bytes = _pack_zstd(db_path, out_zst)
    duration_sec = time.perf_counter() - started_at

    payload = {
        "kind": "config_pack",
        "created_at": _now_iso(),
        "source": {
            "path": str(source_dir),
            "path_rel": _path_for_manifest(source_dir),
        },
        "stats": {
            "entries_total": file_count + dir_count,
            "files_total": file_count,
            "dirs_total": dir_count,
            "source_bytes": total_source_bytes,
            "blob_bytes": total_blob_bytes,
            "db_bytes": db_bytes,
            "zst_bytes": zst_bytes,
            "duration_sec": round(duration_sec, 3),
            "compression_ratio": round(zst_bytes / total_source_bytes, 6) if total_source_bytes else 0.0,
            "ext_counts": dict(ext_counts),
            "object_type_counts": dict(object_type_counts),
            "content_kind_counts": dict(content_kind_counts),
            "db_path": _path_for_manifest(db_path),
            "zst_path": _path_for_manifest(out_zst),
            "sample_verify": verification,
            "sample_paths": sample_paths,
            "zstd_level": zstd_level,
            "excerpt_chars": excerpt_chars,
        },
    }
    _write_manifest(manifest_path, payload)
    if not keep_db:
        db_path.unlink(missing_ok=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack a 1C ConfigDump folder into a compact lossless SQLite DB")
    parser.add_argument("--source-dir", required=True, help="Path to ConfigDump folder")
    parser.add_argument("--db-path", default="build/config.dump.db", help="Plain SQLite output")
    parser.add_argument("--out-zst", default="artifacts/config.dump.db.zst", help="Compressed .db.zst output")
    parser.add_argument("--manifest", default="artifacts/config.dump.manifest.json", help="Manifest path")
    parser.add_argument("--excerpt-chars", type=int, default=1200, help="Text excerpt chars for FTS/search")
    parser.add_argument("--zstd-level", type=int, default=10, help="Per-file zstd compression level")
    parser.add_argument("--sample-verify", type=int, default=25, help="How many sample files to round-trip verify")
    parser.add_argument("--keep-db", dest="keep_db", action="store_true", help="Keep plain .db after packing")
    parser.add_argument("--no-keep-db", dest="keep_db", action="store_false", help="Remove plain .db after packing")
    parser.add_argument("--quiet", action="store_true", help="Reduce progress output")
    parser.set_defaults(keep_db=True)
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source-dir does not exist: {source_dir}")

    payload = build_pack(
        source_dir=source_dir,
        db_path=(REPO_ROOT / args.db_path).resolve(),
        out_zst=(REPO_ROOT / args.out_zst).resolve(),
        manifest_path=(REPO_ROOT / args.manifest).resolve(),
        keep_db=bool(args.keep_db),
        excerpt_chars=max(100, int(args.excerpt_chars)),
        zstd_level=max(1, int(args.zstd_level)),
        sample_verify=max(0, int(args.sample_verify)),
        quiet=bool(args.quiet),
    )
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
