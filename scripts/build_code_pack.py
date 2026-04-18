#!/usr/bin/env python3
"""Build a compact BSL code index pack from a 1C ConfigDump tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.code_index import BslParser, extract_calls, extract_symbols  # noqa: E402
from onec_help.zstd_compat import compress_path as zstd_compress_path  # noqa: E402


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


def _compact_text(value: str, max_chars: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _module_hint(rel_path: Path) -> tuple[str, str, str]:
    parts = rel_path.parts
    if not parts:
        return "", rel_path.stem, rel_path.stem
    object_type = parts[0]
    object_name = parts[1] if len(parts) > 1 else rel_path.stem
    module_kind = rel_path.stem
    if "Forms" in parts:
        form_idx = parts.index("Forms")
        form_name = parts[form_idx + 1] if form_idx + 1 < len(parts) else ""
        module_kind = f"FormModule:{form_name}" if form_name else "FormModule"
    elif len(parts) >= 2 and parts[-2] == "Ext":
        module_kind = rel_path.stem
    elif rel_path.name.lower() == "module.bsl":
        module_kind = "Module"
    return object_type, object_name, module_kind


def _iter_bsl_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.bsl") if path.is_file())


def _create_db(db_path: Path) -> sqlite3.Connection:
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
        CREATE TABLE modules(
            id INTEGER PRIMARY KEY,
            rel_path TEXT NOT NULL UNIQUE,
            object_type TEXT,
            object_name TEXT,
            module_kind TEXT,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            symbol_count INTEGER NOT NULL,
            call_count INTEGER NOT NULL,
            excerpt TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE symbols(
            id INTEGER PRIMARY KEY,
            module_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            is_export INTEGER NOT NULL,
            container TEXT,
            signature TEXT,
            doc_comment TEXT,
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE calls(
            id INTEGER PRIMARY KEY,
            module_id INTEGER NOT NULL,
            caller_name TEXT,
            callee_name TEXT NOT NULL,
            line INTEGER NOT NULL,
            args_count INTEGER NOT NULL,
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE modules_fts
        USING fts5(rel_path, object_type, object_name, module_kind, excerpt, content='modules', content_rowid='id')
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE symbols_fts
        USING fts5(name, signature, doc_comment, content='symbols', content_rowid='id')
        """
    )
    con.commit()
    return con


def _finalize_db(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO modules_fts(rowid, rel_path, object_type, object_name, module_kind, excerpt)
        SELECT id, rel_path, object_type, object_name, module_kind, excerpt FROM modules
        """
    )
    cur.execute(
        """
        INSERT INTO symbols_fts(rowid, name, signature, doc_comment)
        SELECT id, name, signature, doc_comment FROM symbols
        """
    )
    cur.execute("CREATE INDEX idx_symbols_name ON symbols(name)")
    cur.execute("CREATE INDEX idx_symbols_module ON symbols(module_id)")
    cur.execute("CREATE INDEX idx_calls_callee ON calls(callee_name)")
    cur.execute("CREATE INDEX idx_calls_caller ON calls(caller_name)")
    cur.execute("CREATE INDEX idx_calls_module ON calls(module_id)")
    cur.execute("CREATE INDEX idx_modules_object ON modules(object_type, object_name)")
    con.commit()


def _pack_zstd(src_db: Path, out_zst: Path) -> int:
    _ensure_parent(out_zst)
    return zstd_compress_path(src_db, out_zst, level=19)


def build_pack(
    *,
    source_dir: Path,
    db_path: Path,
    out_zst: Path,
    manifest_path: Path,
    keep_db: bool,
    excerpt_chars: int,
) -> dict:
    parser = BslParser()
    con = _create_db(db_path)
    cur = con.cursor()
    files = _iter_bsl_files(source_dir)

    stats = {
        "modules": 0,
        "symbols": 0,
        "calls": 0,
        "source_bytes": 0,
    }
    module_kind_counts: Counter[str] = Counter()
    symbol_kind_counts: Counter[str] = Counter()

    for path in files:
        rel_path = path.relative_to(source_dir)
        data = path.read_bytes()
        parsed = parser.parse_file(path)
        symbols = extract_symbols(parsed)
        calls = extract_calls(parsed)
        object_type, object_name, module_kind = _module_hint(rel_path)
        excerpt = _compact_text(parsed.content, max_chars=excerpt_chars)

        cur.execute(
            """
            INSERT INTO modules(
                rel_path, object_type, object_name, module_kind,
                size_bytes, sha256, symbol_count, call_count, excerpt
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(rel_path).replace("\\", "/"),
                object_type,
                object_name,
                module_kind,
                len(data),
                _sha256_bytes(data),
                len(symbols),
                len(calls),
                excerpt,
            ),
        )
        module_id = int(cur.lastrowid)

        for symbol in symbols:
            cur.execute(
                """
                INSERT INTO symbols(
                    module_id, name, kind, line, end_line, is_export,
                    container, signature, doc_comment
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    module_id,
                    symbol.name,
                    symbol.kind,
                    symbol.line,
                    symbol.end_line,
                    1 if symbol.is_export else 0,
                    symbol.container,
                    symbol.signature,
                    symbol.doc_comment,
                ),
            )
            symbol_kind_counts[symbol.kind] += 1

        for call in calls:
            cur.execute(
                """
                INSERT INTO calls(module_id, caller_name, callee_name, line, args_count)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    module_id,
                    call.caller_name,
                    call.callee_name,
                    call.caller_line,
                    call.callee_args_count,
                ),
            )

        module_kind_counts[module_kind] += 1
        stats["modules"] += 1
        stats["symbols"] += len(symbols)
        stats["calls"] += len(calls)
        stats["source_bytes"] += len(data)

    cur.executemany(
        "INSERT INTO pack_meta(key, value) VALUES(?, ?)",
        [
            ("format", "onec_code_pack_v1"),
            ("created_at", _now_iso()),
            ("source_dir", str(source_dir)),
        ],
    )
    con.commit()
    _finalize_db(con)
    con.close()

    db_bytes = db_path.stat().st_size
    zst_bytes = _pack_zstd(db_path, out_zst)
    manifest = {
        "kind": "code_pack",
        "created_at": _now_iso(),
        "source_dir": _path_for_manifest(source_dir),
        "stats": {
            **stats,
            "module_kinds": dict(sorted(module_kind_counts.items())),
            "symbol_kinds": dict(sorted(symbol_kind_counts.items())),
            "db_bytes": db_bytes,
            "zst_bytes": zst_bytes,
            "db_path": _path_for_manifest(db_path),
            "zst_path": _path_for_manifest(out_zst),
        },
    }
    _ensure_parent(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not keep_db:
        db_path.unlink(missing_ok=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact code.pack.db(.zst) from ConfigDump")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--db-path", default="build/code.pack.db")
    parser.add_argument("--out-zst", default="artifacts/code.pack.db.zst")
    parser.add_argument("--manifest", default="artifacts/code.pack.manifest.json")
    parser.add_argument("--excerpt-chars", type=int, default=500)
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)

    t0 = time.time()
    manifest = build_pack(
        source_dir=source_dir,
        db_path=Path(args.db_path).expanduser().resolve(),
        out_zst=Path(args.out_zst).expanduser().resolve(),
        manifest_path=Path(args.manifest).expanduser().resolve(),
        keep_db=bool(args.keep_db),
        excerpt_chars=max(120, int(args.excerpt_chars)),
    )
    stats = manifest["stats"]
    print(f"modules={stats['modules']} symbols={stats['symbols']} calls={stats['calls']}")
    print(f"source={stats['source_bytes'] / 1024 / 1024:.1f} MB")
    print(f"db={stats['db_bytes'] / 1024 / 1024:.1f} MB ({stats['db_path']})")
    print(f"zst={stats['zst_bytes'] / 1024 / 1024:.1f} MB ({stats['zst_path']})")
    print(f"duration_sec={time.time() - t0:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
