#!/usr/bin/env python3
"""Query local kb.db(.zst) or metadata.kb.db(.zst)."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.runtime_db import ensure_sqlite_db  # noqa: E402


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

    db_path, _temp = ensure_sqlite_db(Path(args.db).expanduser().resolve(), cache_name="query_cache")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
