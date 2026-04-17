#!/usr/bin/env python3
"""Build compact local knowledge packs for 1C agents.

Modes:
- help:     HBK -> unpacked HTML -> structured JSONL -> kb.db.zst
- metadata: metadata XML export XML -> snapshot JSONL -> metadata.kb.db.zst
- all:      run both modes

Output artifacts are designed for local/offline skill usage without Docker/Qdrant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


HELP_JSONL_FILES: tuple[str, ...] = (
    "api_members.jsonl",
    "api_objects.jsonl",
    "api_examples.jsonl",
    "api_links.jsonl",
    "api_topics.jsonl",
)

LANG_PATTERN = re.compile(r"_([a-z]{2})\.hbk$", re.IGNORECASE)


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


def _compact_text(value: Any, max_chars: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _name_from_row(row: dict[str, Any]) -> str:
    for key in ("full_name", "name", "object_name", "member_name", "title", "id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _topic_path_from_row(row: dict[str, Any]) -> str:
    value = row.get("topic_path")
    if isinstance(value, str):
        return value.strip()
    return ""


def _versions_from_row(row: dict[str, Any]) -> list[str]:
    vv = row.get("versions")
    if isinstance(vv, list):
        out = [str(v).strip() for v in vv if str(v).strip()]
        return sorted(set(out))
    v = row.get("version")
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _has_any_version(row: dict[str, Any], selected_versions: set[str]) -> bool:
    if not selected_versions:
        return True
    versions = _versions_from_row(row)
    if not versions:
        return False
    return any(v in selected_versions for v in versions)


def _text_payload_from_help_row(row: dict[str, Any], max_chars: int) -> str:
    parts = [
        _compact_text(row.get("summary"), max_chars=max_chars),
        _compact_text(row.get("description"), max_chars=max_chars),
        _compact_text(row.get("signature"), max_chars=max_chars),
        _compact_text(row.get("syntax"), max_chars=max_chars),
        _compact_text(row.get("purpose"), max_chars=max_chars),
        _compact_text(row.get("returns"), max_chars=max_chars),
        _compact_text(row.get("exceptions"), max_chars=max_chars),
        _compact_text(row.get("text"), max_chars=max_chars),
    ]
    merged = " ".join(p for p in parts if p)
    return _compact_text(merged, max_chars=max_chars)


def _jsonl_iter(path: Path):
    with path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


@dataclass
class BuildStats:
    rows_total: int
    domain_counts: dict[str, int]
    versions_seen: dict[str, int]
    raw_input_bytes: int
    db_bytes: int
    zst_bytes: int
    db_path: str
    zst_path: str


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _safe_stem(path: Path) -> str:
    return re.sub(r"[^\w\-]", "_", path.stem)


def _language_from_filename(name: str) -> str | None:
    match = LANG_PATTERN.search(name)
    return match.group(1).lower() if match else None


def _hbk_label_from_stem(stem: str) -> str:
    return LANG_PATTERN.sub(".hbk", f"{stem}.hbk").rsplit(".", 1)[0]


def _write_hbk_info(
    out_dir: Path,
    *,
    source_file: str,
    label: str,
    version: str,
    language: str,
    file_hash: str,
) -> None:
    payload = {
        "source_file": source_file,
        "label": label,
        "version": version,
        "language": language,
        "hash": file_hash,
    }
    (out_dir / ".hbk_info.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def discover_version_dirs(base_path: Path | str) -> list[tuple[Path, str]]:
    base = Path(base_path).expanduser().resolve()
    if not base.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for child in sorted(base.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        out.append((child, child.name))
    return out


def parse_languages_env(value: str | None) -> list[str] | None:
    if not value or not value.strip():
        return None
    raw = value.strip().lower()
    if raw == "all":
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def collect_hbk_tasks(
    source_dirs_with_versions: list[tuple[Path, str]],
    languages: list[str] | None,
) -> list[tuple[Path, str, str]]:
    tasks: list[tuple[Path, str, str]] = []
    allowed = {item.lower() for item in languages or []}
    for source_dir, version in source_dirs_with_versions:
        for path in sorted(source_dir.rglob("*.hbk")):
            if not path.is_file():
                continue
            language = _language_from_filename(path.name)
            if language is None:
                continue
            if allowed and language not in allowed:
                continue
            tasks.append((path, version, language))
    return tasks


def run_unpack_sync(
    source_dirs_with_versions: list[tuple[Path | str, str]],
    output_dir: Path | str,
    languages: list[str] | None,
    max_workers: int = 4,
    verbose: bool = True,
) -> int:
    from onec_help.help_core.unpack import unpack_hbk

    output_base = Path(output_dir).expanduser().resolve()
    output_base.mkdir(parents=True, exist_ok=True)
    pairs = [(Path(path).expanduser().resolve(), version) for path, version in source_dirs_with_versions]
    tasks = collect_hbk_tasks(pairs, languages)
    count = 0
    for path, version, language in tasks:
        safe_stem = _safe_stem(path)
        out_sub = output_base / version / safe_stem
        out_sub.mkdir(parents=True, exist_ok=True)
        file_hash = _file_sha256(path) or ""
        info_path = out_sub / ".hbk_info.json"
        if info_path.is_file() and file_hash:
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                info = {}
            if info.get("hash") == file_hash:
                if verbose:
                    print(f"[unpack-sync] skip unchanged {version}/{safe_stem}")
                continue
        unpack_hbk(path, out_sub)
        _write_hbk_info(
            out_sub,
            source_file=path.name,
            label=_hbk_label_from_stem(safe_stem),
            version=version,
            language=language,
            file_hash=file_hash,
        )
        if verbose:
            print(f"[unpack-sync] {version}/{safe_stem}")
        count += 1
        if max_workers <= 0:
            break
    return count


def _create_docs_db(db_path: Path) -> sqlite3.Connection:
    _ensure_parent(db_path)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.execute("PRAGMA cache_size=-80000")
    cur.execute(
        """
        CREATE TABLE docs(
            id INTEGER PRIMARY KEY,
            domain TEXT NOT NULL,
            name TEXT,
            topic_path TEXT,
            version TEXT,
            versions_json TEXT,
            payload TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE docs_fts
        USING fts5(name, payload, content='docs', content_rowid='id')
        """
    )
    con.commit()
    return con


def _finalize_docs_db(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("INSERT INTO docs_fts(rowid, name, payload) SELECT id, name, payload FROM docs")
    cur.execute("CREATE INDEX idx_docs_domain ON docs(domain)")
    cur.execute("CREATE INDEX idx_docs_version ON docs(version)")
    con.commit()
    cur.execute("VACUUM")
    con.commit()


def _pack_zstd(src_db: Path, out_zst: Path) -> int:
    _ensure_parent(out_zst)
    cmd = ["zstd", "-q", "-19", "-f", str(src_db), "-o", str(out_zst)]
    subprocess.run(cmd, check=True)
    return out_zst.stat().st_size


def _build_help_jsonl(
    jsonl_dir: Path,
    db_path: Path,
    out_zst: Path,
    selected_versions: set[str],
    max_payload_chars: int,
    keep_db: bool,
) -> BuildStats:
    con = _create_docs_db(db_path)
    cur = con.cursor()

    domain_counts: Counter[str] = Counter()
    versions_seen: Counter[str] = Counter()
    rows_total = 0
    raw_input_bytes = 0

    for file_name in HELP_JSONL_FILES:
        path = jsonl_dir / file_name
        if not path.is_file():
            continue
        domain = file_name.replace(".jsonl", "")
        raw_input_bytes += path.stat().st_size
        batch: list[tuple[str, str, str, str, str, str]] = []
        for row in _jsonl_iter(path):
            if not _has_any_version(row, selected_versions):
                continue
            versions_all = _versions_from_row(row)
            if not versions_all:
                continue
            versions = (
                sorted(v for v in versions_all if v in selected_versions)
                if selected_versions
                else versions_all
            )
            if not versions:
                continue
            primary_version = versions[0]
            for vv in versions:
                versions_seen[vv] += 1
            payload = _text_payload_from_help_row(row, max_chars=max_payload_chars)
            item = (
                domain,
                _name_from_row(row),
                _topic_path_from_row(row),
                primary_version,
                json.dumps(versions, ensure_ascii=False),
                payload,
            )
            batch.append(item)
            if len(batch) >= 2000:
                cur.executemany(
                    """
                    INSERT INTO docs(domain, name, topic_path, version, versions_json, payload)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                rows_total += len(batch)
                domain_counts[domain] += len(batch)
                batch.clear()
        if batch:
            cur.executemany(
                """
                INSERT INTO docs(domain, name, topic_path, version, versions_json, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            rows_total += len(batch)
            domain_counts[domain] += len(batch)
            batch.clear()
        con.commit()

    _finalize_docs_db(con)
    con.close()

    db_bytes = db_path.stat().st_size
    zst_bytes = _pack_zstd(db_path, out_zst)
    if not keep_db:
        db_path.unlink(missing_ok=True)

    return BuildStats(
        rows_total=rows_total,
        domain_counts=dict(domain_counts),
        versions_seen=dict(versions_seen),
        raw_input_bytes=raw_input_bytes,
        db_bytes=db_bytes,
        zst_bytes=zst_bytes,
        db_path=str(db_path),
        zst_path=str(out_zst),
    )


def _resolve_help_jsonl_dir(args: argparse.Namespace) -> Path:
    from onec_help.knowledge.help_structured import build_structured_api_snapshot

    if args.help_jsonl_dir:
        p = Path(args.help_jsonl_dir).expanduser().resolve()
        if not p.is_dir():
            raise FileNotFoundError(f"help-jsonl-dir does not exist: {p}")
        return p

    if not args.hbk_base:
        raise ValueError(
            "Either --help-jsonl-dir or --hbk-base is required for mode=help."
        )

    hbk_base = Path(args.hbk_base).expanduser().resolve()
    if not hbk_base.is_dir():
        raise FileNotFoundError(f"hbk-base does not exist: {hbk_base}")

    work_dir = Path(args.work_dir).expanduser().resolve()
    unpacked_dir = work_dir / "unpacked"
    jsonl_dir = work_dir / "help_structured"
    unpacked_dir.mkdir(parents=True, exist_ok=True)
    jsonl_dir.mkdir(parents=True, exist_ok=True)

    if args.platform:
        sources: list[tuple[str, str]] = []
        for version in args.platform:
            candidate = hbk_base / version
            if candidate.is_dir():
                sources.append((str(candidate), version))
        if not sources:
            raise FileNotFoundError(
                "None of the requested platform versions were found under "
                f"{hbk_base}: {', '.join(args.platform)}"
            )
    else:
        discovered = discover_version_dirs(str(hbk_base))
        sources = [(str(path), version) for path, version in discovered] or [
            (str(hbk_base), hbk_base.name or "default")
        ]
    langs = parse_languages_env(args.languages)

    run_unpack_sync(
        source_dirs_with_versions=sources,
        output_dir=unpacked_dir,
        languages=langs,
        max_workers=max(1, int(args.unpack_workers)),
        verbose=not args.quiet,
    )
    build_structured_api_snapshot(output_dir=jsonl_dir, unpacked_dir=unpacked_dir)
    return jsonl_dir


def _resolve_metadata_snapshot_dirs(args: argparse.Namespace) -> list[Path]:
    from onec_help.knowledge.kd2_metadata import (
        _is_kd2_xml,
        crawl_kd2_xml,
        find_kd2_xml_exports,
        is_kd2_snapshot_dir,
        is_kd2_snapshot_root,
        list_kd2_snapshot_dirs,
        snapshot_dir_for_xml,
        write_kd2_snapshot,
    )
    from onec_help.metadata_index import (
        build_snapshot_from_config_source,
        find_config_roots,
        is_config_source_root,
    )

    if args.metadata_jsonl_dir:
        base = Path(args.metadata_jsonl_dir).expanduser().resolve()
        manifest_path = base / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if str(manifest.get("format") or "").startswith("onec_config_snapshot_"):
                    return [base]
            except (OSError, ValueError, TypeError):
                pass
        if is_kd2_snapshot_dir(base):
            return [base]
        if is_kd2_snapshot_root(base):
            return list_kd2_snapshot_dirs(base)
        raise FileNotFoundError(
            f"metadata-jsonl-dir is not a snapshot dir/root: {base}"
        )

    if args.config_source:
        source = Path(args.config_source).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"config-source does not exist: {source}")
        config_roots = [source] if is_config_source_root(source) else find_config_roots(source)
        if not config_roots:
            raise FileNotFoundError(f"No Configuration.xml roots found in config-source: {source}")
        output_root = Path(args.work_dir).expanduser().resolve() / "config_metadata_snapshot"
        output_root.mkdir(parents=True, exist_ok=True)
        out_dirs: list[Path] = []
        for config_root in config_roots:
            target_name = config_root.name if config_root != source else source.name
            out_dir = output_root / target_name.lower()
            out_dirs.append(build_snapshot_from_config_source(config_root, out_dir))
        return out_dirs

    if not args.metadata_source:
        raise ValueError(
            "Either --metadata-jsonl-dir, --config-source, or --metadata-source is required for mode=metadata."
        )

    source = Path(args.metadata_source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"metadata-source does not exist: {source}")

    if is_kd2_snapshot_dir(source):
        return [source]
    if is_kd2_snapshot_root(source):
        return list_kd2_snapshot_dirs(source)

    xml_files: list[Path] = []
    if source.is_file() and _is_kd2_xml(source):
        xml_files = [source]
    elif source.is_dir():
        xml_files = find_kd2_xml_exports(source)
    if not xml_files:
        raise FileNotFoundError(
            f"No KD2 XML exports found in metadata-source: {source}"
        )

    output_root = Path(args.work_dir).expanduser().resolve() / "metadata_snapshot"
    output_root.mkdir(parents=True, exist_ok=True)
    out_dirs: list[Path] = []
    for xml_path in xml_files:
        crawl = crawl_kd2_xml(xml_path)
        out_dir = snapshot_dir_for_xml(output_root, xml_path)
        write_kd2_snapshot(crawl, out_dir)
        out_dirs.append(out_dir)
    return out_dirs


def _metadata_payload_object(row: dict[str, Any], max_payload_chars: int) -> str:
    parts = [
        _compact_text(row.get("object_type"), max_chars=max_payload_chars),
        _compact_text(row.get("name"), max_chars=max_payload_chars),
        _compact_text(row.get("full_name"), max_chars=max_payload_chars),
        _compact_text(row.get("path"), max_chars=max_payload_chars),
    ]
    return _compact_text(" ".join(p for p in parts if p), max_chars=max_payload_chars)


def _metadata_payload_field(row: dict[str, Any], max_payload_chars: int) -> str:
    field_name = str(row.get("name") or row.get("field_name") or "").strip()
    parts = [
        _compact_text(row.get("object_id"), max_chars=max_payload_chars),
        _compact_text(row.get("object_name"), max_chars=max_payload_chars),
        _compact_text(field_name, max_chars=max_payload_chars),
        _compact_text(row.get("synonym"), max_chars=max_payload_chars),
        _compact_text(row.get("kind") or row.get("field_kind"), max_chars=max_payload_chars),
        _compact_text(row.get("group") or row.get("group_name"), max_chars=max_payload_chars),
        _compact_text(row.get("tabular_section"), max_chars=max_payload_chars),
        _compact_text(row.get("type") or row.get("type_presentation"), max_chars=max_payload_chars),
        _compact_text(row.get("defined_type"), max_chars=max_payload_chars),
        _compact_text(row.get("constant_bsl_hint"), max_chars=max_payload_chars),
    ]
    return _compact_text(" ".join(p for p in parts if p), max_chars=max_payload_chars)


def _metadata_field_identity(row: dict[str, Any]) -> tuple[str, str]:
    field_name = str(row.get("name") or row.get("field_name") or "").strip()
    object_id = str(row.get("object_id") or "").strip()
    group_name = str(row.get("group") or row.get("group_name") or "").strip()
    tabular_section = str(row.get("tabular_section") or "").strip()
    form_name = str(row.get("form_name") or "").strip()

    if group_name == "tabular_sections":
        topic_path = f"{object_id}.{field_name}" if object_id and field_name else object_id
        return field_name, topic_path

    if group_name == "tabular_section_requisites":
        display_name = (
            f"{tabular_section}.{field_name}" if tabular_section and field_name else field_name
        )
        topic_parts = [part for part in (object_id, tabular_section, field_name) if part]
        return display_name, ".".join(topic_parts)

    if group_name in {"form_attributes", "form_commands"}:
        display_parts = [part for part in (form_name, field_name) if part]
        display_name = ".".join(display_parts) if display_parts else field_name
        topic_parts = [part for part in (object_id, "Forms", form_name, field_name) if part]
        return display_name, ".".join(topic_parts)

    topic_path = f"{object_id}.{field_name}" if object_id and field_name else object_id
    return field_name, topic_path


def _build_metadata_jsonl(
    snapshot_dirs: list[Path],
    db_path: Path,
    out_zst: Path,
    selected_config_versions: set[str],
    max_payload_chars: int,
    keep_db: bool,
) -> BuildStats:
    con = _create_docs_db(db_path)
    cur = con.cursor()

    domain_counts: Counter[str] = Counter()
    versions_seen: Counter[str] = Counter()
    rows_total = 0
    raw_input_bytes = 0

    for snapshot_dir in snapshot_dirs:
        manifest_path = snapshot_dir / "manifest.json"
        objects_path = snapshot_dir / "objects.jsonl"
        fields_path = snapshot_dir / "fields.jsonl"
        if not (manifest_path.is_file() and objects_path.is_file() and fields_path.is_file()):
            continue

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cfg_version = str(manifest.get("config_version") or "0.0.0.0").strip()
        if selected_config_versions and cfg_version not in selected_config_versions:
            continue

        raw_input_bytes += (
            manifest_path.stat().st_size + objects_path.stat().st_size + fields_path.stat().st_size
        )

        for row in _jsonl_iter(objects_path):
            payload = _metadata_payload_object(row, max_payload_chars=max_payload_chars)
            name = _name_from_row(row)
            topic_path = str(row.get("path") or row.get("id") or "").strip()
            cur.execute(
                """
                INSERT INTO docs(domain, name, topic_path, version, versions_json, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "metadata_objects",
                    name,
                    topic_path,
                    cfg_version,
                    json.dumps([cfg_version], ensure_ascii=False),
                    payload,
                ),
            )
            rows_total += 1
            domain_counts["metadata_objects"] += 1
            versions_seen[cfg_version] += 1

        for row in _jsonl_iter(fields_path):
            payload = _metadata_payload_field(row, max_payload_chars=max_payload_chars)
            name, topic_path = _metadata_field_identity(row)
            cur.execute(
                """
                INSERT INTO docs(domain, name, topic_path, version, versions_json, payload)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "metadata_fields",
                    name,
                    topic_path,
                    cfg_version,
                    json.dumps([cfg_version], ensure_ascii=False),
                    payload,
                ),
            )
            rows_total += 1
            domain_counts["metadata_fields"] += 1
            versions_seen[cfg_version] += 1
        con.commit()

    _finalize_docs_db(con)
    con.close()

    db_bytes = db_path.stat().st_size
    zst_bytes = _pack_zstd(db_path, out_zst)
    if not keep_db:
        db_path.unlink(missing_ok=True)

    return BuildStats(
        rows_total=rows_total,
        domain_counts=dict(domain_counts),
        versions_seen=dict(versions_seen),
        raw_input_bytes=raw_input_bytes,
        db_bytes=db_bytes,
        zst_bytes=zst_bytes,
        db_path=str(db_path),
        zst_path=str(out_zst),
    )


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_stats(title: str, stats: BuildStats) -> None:
    print(f"{title}: rows={stats.rows_total}")
    print(f"  input={stats.raw_input_bytes / 1024 / 1024:.1f} MB")
    print(f"  db={stats.db_bytes / 1024 / 1024:.1f} MB ({stats.db_path})")
    print(f"  zst={stats.zst_bytes / 1024 / 1024:.1f} MB ({stats.zst_path})")
    if stats.domain_counts:
        print(f"  domains={stats.domain_counts}")
    if stats.versions_seen:
        print(f"  versions={dict(sorted(stats.versions_seen.items()))}")


def _run_help(args: argparse.Namespace) -> None:
    t0 = time.time()
    jsonl_dir = _resolve_help_jsonl_dir(args)
    versions = set(args.platform or [])
    stats = _build_help_jsonl(
        jsonl_dir=jsonl_dir,
        db_path=Path(args.db_path).expanduser().resolve(),
        out_zst=Path(args.out_zst).expanduser().resolve(),
        selected_versions=versions,
        max_payload_chars=max(200, int(args.max_payload_chars)),
        keep_db=bool(args.keep_db),
    )
    manifest = {
        "kind": "help",
        "created_at": _now_iso(),
        "duration_sec": round(time.time() - t0, 3),
        "source_jsonl_dir": str(jsonl_dir),
        "source_jsonl_dir_manifest": _path_for_manifest(jsonl_dir),
        "selected_platforms": sorted(list(versions)),
        "stats": {
            "rows_total": stats.rows_total,
            "domain_counts": stats.domain_counts,
            "versions_seen": stats.versions_seen,
            "raw_input_bytes": stats.raw_input_bytes,
            "db_bytes": stats.db_bytes,
            "zst_bytes": stats.zst_bytes,
            "db_path": _path_for_manifest(stats.db_path),
            "zst_path": _path_for_manifest(stats.zst_path),
        },
    }
    _write_manifest(Path(args.manifest).expanduser().resolve(), manifest)
    _print_stats("help kb built", stats)


def _run_metadata(args: argparse.Namespace) -> None:
    t0 = time.time()
    snapshot_dirs = _resolve_metadata_snapshot_dirs(args)
    cfg_versions = set(args.config_version or [])
    stats = _build_metadata_jsonl(
        snapshot_dirs=snapshot_dirs,
        db_path=Path(args.db_path).expanduser().resolve(),
        out_zst=Path(args.out_zst).expanduser().resolve(),
        selected_config_versions=cfg_versions,
        max_payload_chars=max(200, int(args.max_payload_chars)),
        keep_db=bool(args.keep_db),
    )
    manifest = {
        "kind": "metadata",
        "created_at": _now_iso(),
        "duration_sec": round(time.time() - t0, 3),
        "snapshot_dirs": [str(p) for p in snapshot_dirs],
        "snapshot_dirs_manifest": [_path_for_manifest(p) for p in snapshot_dirs],
        "selected_config_versions": sorted(list(cfg_versions)),
        "stats": {
            "rows_total": stats.rows_total,
            "domain_counts": stats.domain_counts,
            "versions_seen": stats.versions_seen,
            "raw_input_bytes": stats.raw_input_bytes,
            "db_bytes": stats.db_bytes,
            "zst_bytes": stats.zst_bytes,
            "db_path": _path_for_manifest(stats.db_path),
            "zst_path": _path_for_manifest(stats.zst_path),
        },
    }
    _write_manifest(Path(args.manifest).expanduser().resolve(), manifest)
    _print_stats("metadata kb built", stats)


def _run_all(args: argparse.Namespace) -> None:
    help_ns = argparse.Namespace(**vars(args))
    help_ns.mode = "help"
    help_ns.db_path = args.help_db_path
    help_ns.out_zst = args.help_out_zst
    help_ns.manifest = args.help_manifest
    _run_help(help_ns)

    metadata_ns = argparse.Namespace(**vars(args))
    metadata_ns.mode = "metadata"
    metadata_ns.db_path = args.metadata_db_path
    metadata_ns.out_zst = args.metadata_out_zst
    metadata_ns.manifest = args.metadata_manifest
    _run_metadata(metadata_ns)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build compact local KB packs for 1C agent skills."
    )
    sub = p.add_subparsers(dest="mode", required=True)

    def add_common_help_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--help-jsonl-dir",
            type=str,
            default=None,
            help="Use existing help JSONL dir (api_*.jsonl) as input.",
        )
        sp.add_argument(
            "--hbk-base",
            type=str,
            default=None,
            help="Path to .hbk source dir (used when help-jsonl-dir is not provided).",
        )
        sp.add_argument(
            "--languages",
            type=str,
            default="ru",
            help="Languages for unpack-sync when hbk-base is used (default: ru).",
        )
        sp.add_argument(
            "--platform",
            action="append",
            default=[],
            help="Include only these platform versions; repeat flag for multiple versions.",
        )
        sp.add_argument(
            "--unpack-workers",
            type=int,
            default=4,
            help="Workers for unpack-sync when hbk-base is used (default: 4).",
        )
        sp.add_argument(
            "--quiet",
            action="store_true",
            help="Less output during unpack/build steps.",
        )

    def add_common_metadata_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--metadata-jsonl-dir",
            type=str,
            default=None,
            help="Use existing metadata snapshot dir/root as input.",
        )
        sp.add_argument(
            "--config-source",
            type=str,
            default=None,
            help="Primary source-first mode: ConfigDump root/parent with Configuration.xml.",
        )
        sp.add_argument(
            "--metadata-source",
            type=str,
            default=None,
            help="Optional fallback/import mode: metadata XML export XML file/dir OR snapshot dir/root.",
        )
        sp.add_argument(
            "--config-version",
            action="append",
            default=[],
            help="Include only these config versions; repeat flag for multiple versions.",
        )

    def add_common_build_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--work-dir",
            type=str,
            default="build/kb_work",
            help="Work directory for intermediate unpack/snapshot files.",
        )
        sp.add_argument(
            "--max-payload-chars",
            type=int,
            default=3000,
            help="Max chars for compact payload text stored in DB.",
        )
        sp.add_argument(
            "--keep-db",
            action="store_true",
            default=True,
            help="Keep plain .db file after zstd pack (default: true).",
        )
        sp.add_argument(
            "--no-keep-db",
            dest="keep_db",
            action="store_false",
            help="Remove plain .db file after zstd pack.",
        )

    p_help = sub.add_parser("help", help="Build help KB pack (HBK/JSONL -> kb.db.zst)")
    add_common_help_flags(p_help)
    add_common_build_flags(p_help)
    p_help.add_argument("--db-path", type=str, default="build/kb.db")
    p_help.add_argument("--out-zst", type=str, default="artifacts/kb.db.zst")
    p_help.add_argument("--manifest", type=str, default="artifacts/kb.manifest.json")
    p_help.set_defaults(func=_run_help)

    p_meta = sub.add_parser(
        "metadata", help="Build metadata KB pack (XML/snapshot -> metadata.kb.db.zst)"
    )
    add_common_metadata_flags(p_meta)
    add_common_build_flags(p_meta)
    p_meta.add_argument("--db-path", type=str, default="build/metadata.kb.db")
    p_meta.add_argument("--out-zst", type=str, default="artifacts/metadata.kb.db.zst")
    p_meta.add_argument("--manifest", type=str, default="artifacts/metadata.kb.manifest.json")
    p_meta.set_defaults(func=_run_metadata)

    p_all = sub.add_parser("all", help="Build both help and metadata packs")
    add_common_help_flags(p_all)
    add_common_metadata_flags(p_all)
    add_common_build_flags(p_all)
    p_all.add_argument("--help-db-path", type=str, default="build/kb.db")
    p_all.add_argument("--help-out-zst", type=str, default="artifacts/kb.db.zst")
    p_all.add_argument("--help-manifest", type=str, default="artifacts/kb.manifest.json")
    p_all.add_argument("--metadata-db-path", type=str, default="build/metadata.kb.db")
    p_all.add_argument("--metadata-out-zst", type=str, default="artifacts/metadata.kb.db.zst")
    p_all.add_argument(
        "--metadata-manifest", type=str, default="artifacts/metadata.kb.manifest.json"
    )
    p_all.set_defaults(func=_run_all)

    return p


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error: command failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # pragma: no cover - defensive
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
