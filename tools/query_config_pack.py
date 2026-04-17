#!/usr/bin/env python3
"""Inspect and extract data from config.dump.db(.zst)."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.runtime_db import ensure_sqlite_db  # noqa: E402
from onec_help.zstd_compat import decompress as zstd_decompress  # noqa: E402


def _tokenize_fts_query(query: str) -> str:
    tokens = [token for token in re.split(r"[^\w\u0400-\u04FF]+", query, flags=re.UNICODE) if token]
    return " AND ".join(tokens)


def cmd_stats(db_path: Path) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    meta = dict(cur.execute("SELECT key, value FROM pack_meta").fetchall())
    counts = cur.execute(
        """
        SELECT entry_type, COUNT(*), COALESCE(SUM(size_bytes), 0), COALESCE(SUM(blob_size), 0)
        FROM entries
        GROUP BY entry_type
        ORDER BY entry_type
        """
    ).fetchall()
    payload = {
        "db_path": str(db_path),
        "meta": meta,
        "counts": [
            {"entry_type": row[0], "count": row[1], "size_bytes": row[2], "blob_bytes": row[3]}
            for row in counts
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    con.close()
    return 0


def cmd_find(db_path: Path, query: str, limit: int) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT rel_path, entry_type, size_bytes, object_type, object_name, content_kind
        FROM entries
        WHERE lower(rel_path) = lower(?) OR lower(object_name) = lower(?)
        LIMIT ?
        """,
        (query, query, limit),
    ).fetchall()
    if not rows:
        like_query = f"%{query}%"
        rows = cur.execute(
            """
            SELECT rel_path, entry_type, size_bytes, object_type, object_name, content_kind
            FROM entries
            WHERE rel_path LIKE ? OR object_name LIKE ?
            ORDER BY length(rel_path), rel_path
            LIMIT ?
            """,
            (like_query, like_query, limit),
        ).fetchall()
    if not rows:
        fts_query = _tokenize_fts_query(query)
        if fts_query:
            rows = cur.execute(
                """
                SELECT e.rel_path, e.entry_type, e.size_bytes, e.object_type, e.object_name, e.content_kind
                FROM entries_fts
                JOIN entries e ON e.id = entries_fts.rowid
                WHERE entries_fts MATCH ?
                ORDER BY bm25(entries_fts), length(e.rel_path), e.rel_path
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
    for idx, row in enumerate(rows, 1):
        rel_path, entry_type, size_bytes, object_type, object_name, content_kind = row
        print(f"{idx}. [{entry_type}] {rel_path}")
        print(f"   object: {object_type}/{object_name}")
        print(f"   size: {size_bytes or 0} bytes")
        print(f"   content: {content_kind or ''}")
    con.close()
    return 0


def _fetch_blob(cur: sqlite3.Cursor, rel_path: str):
    return cur.execute(
        """
        SELECT e.entry_type, e.content_kind, e.text_encoding, e.compression, b.data
        FROM entries e
        LEFT JOIN file_blobs b ON b.entry_id = e.id
        WHERE e.rel_path = ?
        """,
        (rel_path,),
    ).fetchone()


def cmd_read(db_path: Path, rel_path: str) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    row = _fetch_blob(cur, rel_path)
    if row is None:
        raise FileNotFoundError(rel_path)
    entry_type, content_kind, encoding, compression, blob = row
    if entry_type != "file":
        raise IsADirectoryError(rel_path)
    data = zstd_decompress(blob) if compression == "zstd" else blob
    if content_kind != "text":
        raise ValueError(f"{rel_path} is binary; use extract instead")
    print(data.decode(encoding or "utf-8", errors="replace"))
    con.close()
    return 0


def cmd_extract(db_path: Path, rel_path: str, output_path: Path) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    row = _fetch_blob(cur, rel_path)
    if row is None:
        raise FileNotFoundError(rel_path)
    entry_type, _content_kind, _encoding, compression, blob = row
    if entry_type != "file":
        raise IsADirectoryError(rel_path)
    data = zstd_decompress(blob) if compression == "zstd" else blob
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    print(output_path)
    con.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect config.dump.db(.zst)")
    parser.add_argument("--db", required=True, help="Path to config.dump.db or config.dump.db.zst")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show pack metadata and entry counts")

    find_p = sub.add_parser("find", help="Find entries by path/name/text excerpt")
    find_p.add_argument("--q", required=True)
    find_p.add_argument("--limit", type=int, default=20)

    read_p = sub.add_parser("read", help="Print a text file from the pack")
    read_p.add_argument("--path", required=True)

    extract_p = sub.add_parser("extract", help="Extract one file from the pack")
    extract_p.add_argument("--path", required=True)
    extract_p.add_argument("--out", required=True)

    args = parser.parse_args()
    db_path, _temp = ensure_sqlite_db(Path(args.db).expanduser().resolve(), cache_name="config_pack_cache")

    if args.command == "stats":
        return cmd_stats(db_path)
    if args.command == "find":
        return cmd_find(db_path, args.q, args.limit)
    if args.command == "read":
        return cmd_read(db_path, args.path)
    if args.command == "extract":
        return cmd_extract(db_path, args.path, Path(args.out).expanduser().resolve())
    raise ValueError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
