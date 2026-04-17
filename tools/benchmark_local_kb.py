#!/usr/bin/env python3
"""Basic query latency benchmark for local compact KB artifacts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
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


def _run_bench(path: Path, queries: list[str], loops: int = 5) -> None:
    db_path, _temp = ensure_sqlite_db(path, cache_name="benchmark_cache")
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
    parser = argparse.ArgumentParser(description="Query latency benchmark for local compact KB artifacts")
    parser.add_argument("--workspace-root", default=None, help="Workspace root with .onec/packs")
    parser.add_argument("--artifacts-dir", default=None, help="Explicit artifacts/packs directory")
    parser.add_argument("--loops", type=int, default=5)
    args = parser.parse_args()

    pack_paths = _resolve_pack_paths(args.workspace_root, args.artifacts_dir)
    help_paths = [path for path in pack_paths["platform"] if path.exists()]
    for help_path in help_paths[:1]:
        _run_bench(
            help_path,
            ["Глобальный контекст.ПрочитатьJSON", "HTTPСоединение.Получить", "ТаблицаЗначений"],
            loops=args.loops,
        )
    metadata_paths = [path for path in pack_paths["metadata"] if path.exists()]
    if metadata_paths:
        for metadata_path in metadata_paths:
            _run_bench(
                metadata_path,
            ["Document.РеализацияТоваровУслуг", "Организация", "Товары"],
                loops=args.loops,
            )
    else:
        print("metadata pack is absent; skipping metadata benchmark")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
