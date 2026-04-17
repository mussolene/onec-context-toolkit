#!/usr/bin/env python3
"""Query compact code.pack.db(.zst) artifacts."""

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
    cache_dir = REPO_ROOT / "build" / "code_pack_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    cache_name = f"{path.name.removesuffix('.zst')}.{stat.st_size}.{stat.st_mtime_ns}.db"
    return cache_dir / cache_name


def _extract_once(path: Path, out_path: Path) -> None:
    fd, tmp = tempfile.mkstemp(prefix="code_pack_", suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp)
    tmp_path.unlink(missing_ok=True)
    try:
        subprocess.run(["zstd", "-q", "-d", "-f", str(path), "-o", str(tmp_path)], check=True)
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _ensure_db(path: Path) -> Path:
    if path.suffix != ".zst":
        return path
    for candidate in _plain_db_candidates(path):
        if candidate.is_file():
            return candidate
    cache_path = _cached_extract_path(path)
    if not cache_path.is_file():
        _extract_once(path, cache_path)
    return cache_path


def _tokenize_fts_query(query: str) -> str:
    tokens = [token for token in re.split(r"[^\w\u0400-\u04FF]+", query, flags=re.UNICODE) if token]
    return " AND ".join(tokens)


def cmd_stats(db_path: Path) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    meta = dict(cur.execute("SELECT key, value FROM pack_meta").fetchall())
    counts = {
        "modules": cur.execute("SELECT count(*) FROM modules").fetchone()[0],
        "symbols": cur.execute("SELECT count(*) FROM symbols").fetchone()[0],
        "calls": cur.execute("SELECT count(*) FROM calls").fetchone()[0],
    }
    print(json.dumps({"db_path": str(db_path), "meta": meta, "counts": counts}, ensure_ascii=False, indent=2))
    con.close()
    return 0


def cmd_modules(db_path: Path, query: str, limit: int) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT rel_path, object_type, object_name, module_kind, symbol_count, call_count
        FROM modules
        WHERE lower(rel_path)=lower(?) OR lower(object_name)=lower(?)
        LIMIT ?
        """,
        (query, query, limit),
    ).fetchall()
    if not rows:
        fts_query = _tokenize_fts_query(query)
        if fts_query:
            rows = cur.execute(
                """
                SELECT m.rel_path, m.object_type, m.object_name, m.module_kind, m.symbol_count, m.call_count
                FROM modules_fts
                JOIN modules m ON m.id = modules_fts.rowid
                WHERE modules_fts MATCH ?
                ORDER BY bm25(modules_fts), length(m.rel_path), m.rel_path
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
    for idx, row in enumerate(rows, 1):
        rel_path, object_type, object_name, module_kind, symbol_count, call_count = row
        print(f"{idx}. {rel_path}")
        print(f"   object: {object_type}/{object_name}")
        print(f"   module: {module_kind}")
        print(f"   symbols={symbol_count} calls={call_count}")
    con.close()
    return 0


def cmd_symbols(db_path: Path, query: str, limit: int) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT s.name, s.kind, s.line, s.is_export, s.container, s.signature, m.rel_path
        FROM symbols s
        JOIN modules m ON m.id = s.module_id
        WHERE lower(s.name)=lower(?) OR lower(s.signature)=lower(?)
        ORDER BY m.rel_path, s.line
        LIMIT ?
        """,
        (query, query, limit),
    ).fetchall()
    if not rows:
        fts_query = _tokenize_fts_query(query)
        if fts_query:
            rows = cur.execute(
                """
                SELECT s.name, s.kind, s.line, s.is_export, s.container, s.signature, m.rel_path
                FROM symbols_fts
                JOIN symbols s ON s.id = symbols_fts.rowid
                JOIN modules m ON m.id = s.module_id
                WHERE symbols_fts MATCH ?
                ORDER BY bm25(symbols_fts), length(m.rel_path), s.line
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
    for idx, row in enumerate(rows, 1):
        name, kind, line, is_export, container, signature, rel_path = row
        print(f"{idx}. {name} [{kind}] {rel_path}:{line}")
        print(f"   export: {'yes' if is_export else 'no'}")
        if container:
            print(f"   container: {container}")
        if signature:
            print(f"   signature: {signature}")
    con.close()
    return 0


def cmd_callers(db_path: Path, symbol_name: str, limit: int) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT c.caller_name, c.line, m.rel_path
        FROM calls c
        JOIN modules m ON m.id = c.module_id
        WHERE lower(c.callee_name)=lower(?)
        ORDER BY m.rel_path, c.line
        LIMIT ?
        """,
        (symbol_name, limit),
    ).fetchall()
    for idx, row in enumerate(rows, 1):
        caller_name, line, rel_path = row
        print(f"{idx}. {rel_path}:{line}")
        print(f"   caller: {caller_name or '<module>'}")
    con.close()
    return 0


def cmd_callees(db_path: Path, symbol_name: str, limit: int) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT c.callee_name, count(*)
        FROM calls c
        WHERE lower(c.caller_name)=lower(?)
        GROUP BY c.callee_name
        ORDER BY count(*) DESC, c.callee_name
        LIMIT ?
        """,
        (symbol_name, limit),
    ).fetchall()
    for idx, row in enumerate(rows, 1):
        callee_name, count = row
        print(f"{idx}. {callee_name} ({count})")
    con.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Query compact code pack")
    parser.add_argument("--db", default="artifacts/code.pack.db.zst")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show pack stats")

    modules_p = sub.add_parser("modules", help="Find code modules")
    modules_p.add_argument("--q", required=True)
    modules_p.add_argument("--limit", type=int, default=20)

    symbols_p = sub.add_parser("symbols", help="Find symbols")
    symbols_p.add_argument("--q", required=True)
    symbols_p.add_argument("--limit", type=int, default=20)

    callers_p = sub.add_parser("callers", help="Show callers of a symbol")
    callers_p.add_argument("--symbol", required=True)
    callers_p.add_argument("--limit", type=int, default=20)

    callees_p = sub.add_parser("callees", help="Show callees of a symbol")
    callees_p.add_argument("--symbol", required=True)
    callees_p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    db_path = _ensure_db(Path(args.db).expanduser().resolve())
    t0 = time.perf_counter()

    if args.command == "stats":
        rc = cmd_stats(db_path)
    elif args.command == "modules":
        rc = cmd_modules(db_path, args.q, args.limit)
    elif args.command == "symbols":
        rc = cmd_symbols(db_path, args.q, args.limit)
    elif args.command == "callers":
        rc = cmd_callers(db_path, args.symbol, args.limit)
    elif args.command == "callees":
        rc = cmd_callees(db_path, args.symbol, args.limit)
    else:
        raise ValueError(args.command)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"\nelapsed_ms: {elapsed_ms:.1f}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
