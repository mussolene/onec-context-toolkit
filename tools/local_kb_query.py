#!/usr/bin/env python3
"""Query local kb.db(.zst) or metadata.kb.db(.zst)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _manifest_path_for_zst(path: Path) -> Path | None:
    if not path.name.endswith(".db.zst"):
        return None
    manifest_name = path.name.replace(".db.zst", ".manifest.json")
    manifest_path = path.with_name(manifest_name)
    return manifest_path if manifest_path.is_file() else None


def _plain_db_candidates(path: Path) -> list[Path]:
    candidates: list[Path] = []
    if path.suffix == ".zst":
        candidates.append(path.with_suffix(""))
        manifest_path = _manifest_path_for_zst(path)
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


def _cached_extract_path(path: Path) -> Path:
    cache_dir = REPO_ROOT / "build" / "query_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    cache_name = f"{path.name.removesuffix('.zst')}.{stat.st_size}.{stat.st_mtime_ns}.db"
    return cache_dir / cache_name


def _extract_once(path: Path, out_path: Path) -> None:
    fd, tmp = tempfile.mkstemp(prefix="kb_query_", suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp)
    tmp_path.unlink(missing_ok=True)
    try:
        subprocess.run(["zstd", "-q", "-d", "-f", str(path), "-o", str(tmp_path)], check=True)
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _ensure_db(path: Path) -> tuple[Path, bool]:
    if path.suffix != ".zst":
        return path, False
    for candidate in _plain_db_candidates(path):
        if candidate.is_file():
            return candidate, False
    cache_path = _cached_extract_path(path)
    if not cache_path.is_file():
        _extract_once(path, cache_path)
    return cache_path, False


def _tokenize_fts_query(query: str) -> str:
    tokens = [token for token in re.split(r"[^\w\u0400-\u04FF]+", query, flags=re.UNICODE) if token]
    return " AND ".join(tokens)


def _exact_rows(cur: sqlite3.Cursor, query: str, limit: int, domain: str | None, version: str | None):
    sql = [
        "SELECT domain, name, topic_path, substr(payload,1,200)",
        "FROM docs",
        "WHERE (lower(name)=lower(?) OR lower(topic_path)=lower(?))",
    ]
    params: list[object] = [query, query]
    if domain:
        sql.append("AND domain = ?")
        params.append(domain)
    if version:
        sql.append("AND version = ?")
        params.append(version)
    sql.append("LIMIT ?")
    params.append(limit)
    return cur.execute("\n".join(sql), params).fetchall()


def _fts_rows(
    cur: sqlite3.Cursor,
    fts_query: str,
    original_query: str,
    limit: int,
    domain: str | None,
    version: str | None,
):
    sql = [
        "SELECT d.domain, d.name, d.topic_path, substr(d.payload,1,200), bm25(docs_fts) AS rank",
        "FROM docs_fts",
        "JOIN docs d ON d.id = docs_fts.rowid",
        "WHERE docs_fts MATCH ?",
    ]
    params: list[object] = [fts_query]
    if domain:
        sql.append("AND d.domain = ?")
        params.append(domain)
    if version:
        sql.append("AND d.version = ?")
        params.append(version)
    sql.append(
        "ORDER BY rank, CASE WHEN lower(d.name)=lower(?) OR lower(d.topic_path)=lower(?) THEN 0 ELSE 1 END, length(d.name)"
    )
    params.extend([original_query, original_query])
    sql.append("LIMIT ?")
    params.append(limit)
    rows = cur.execute("\n".join(sql), params).fetchall()
    return [row[:4] for row in rows]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="Path to kb.db or kb.db.zst")
    p.add_argument("--q", required=True, help="FTS query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--domain", help="Restrict to a domain like api_members or metadata_fields")
    p.add_argument("--version", help="Restrict to one platform/config version")
    p.add_argument("--exact", action="store_true", help="Only use exact name/topic lookup")
    args = p.parse_args()

    db_path, temp = _ensure_db(Path(args.db).expanduser().resolve())
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        t0 = time.perf_counter()
        rows = _exact_rows(cur, args.q, args.limit, args.domain, args.version)
        if not rows and not args.exact:
            fts_query = _tokenize_fts_query(args.q)
            if fts_query:
                rows = _fts_rows(
                    cur,
                    fts_query,
                    args.q,
                    args.limit,
                    args.domain,
                    args.version,
                )
        for i, (domain, name, topic, payload) in enumerate(rows, 1):
            print(f"{i}. [{domain}] {name}")
            print(f"   topic: {topic}")
            if payload:
                print(f"   payload: {payload}")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"\nquery_ms: {elapsed_ms:.1f}")
        con.close()
    finally:
        if temp:
            db_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
