#!/usr/bin/env python3
"""Basic query latency benchmark for local compact KB artifacts."""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "artifacts"


def _ensure_db(path: Path) -> tuple[Path, bool]:
    if path.suffix != ".zst":
        return path, False
    fd, tmp = tempfile.mkstemp(prefix="bench_kb_", suffix=".db")
    Path(tmp).unlink(missing_ok=True)
    subprocess.run(["zstd", "-q", "-d", "-f", str(path), "-o", tmp], check=True)
    return Path(tmp), True


def _run_bench(path: Path, queries: list[str], loops: int = 5) -> None:
    db_path, temp = _ensure_db(path)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        timings: list[float] = []
        for _ in range(loops):
            for query in queries:
                started = time.perf_counter()
                cur.execute(
                    """
                    SELECT domain, name
                    FROM docs
                    WHERE lower(name)=lower(?) OR docs.id IN (
                        SELECT rowid FROM docs_fts WHERE docs_fts MATCH ?
                    )
                    LIMIT 5
                    """,
                    (query, " AND ".join(token for token in query.replace(".", " ").split() if token)),
                ).fetchall()
                timings.append((time.perf_counter() - started) * 1000)
        con.close()
        print(
            f"{path.name}: size_mb={path.stat().st_size / 1024 / 1024:.2f} runs={len(timings)} avg_ms={statistics.mean(timings):.2f} "
            f"p95_ms={sorted(timings)[max(0, int(len(timings) * 0.95) - 1)]:.2f}"
        )
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
    parser = argparse.ArgumentParser(description="Query latency benchmark for local compact KB artifacts")
    parser.add_argument("--workspace-root", default=None, help="Workspace root with .onec/packs")
    parser.add_argument("--artifacts-dir", default=None, help="Explicit artifacts/packs directory")
    parser.add_argument("--loops", type=int, default=5)
    args = parser.parse_args()

    artifacts_dir = _resolve_artifacts_dir(args.workspace_root, args.artifacts_dir)
    help_path = artifacts_dir / "kb.db.zst"
    if help_path.exists():
        _run_bench(
            help_path,
            ["Глобальный контекст.ПрочитатьJSON", "HTTPСоединение.Получить", "ТаблицаЗначений"],
            loops=args.loops,
        )
    metadata_path = artifacts_dir / "metadata.kb.db.zst"
    if metadata_path.exists():
        _run_bench(
            metadata_path,
            ["Document.РеализацияТоваровУслуг", "Организация", "Товары"],
            loops=args.loops,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
