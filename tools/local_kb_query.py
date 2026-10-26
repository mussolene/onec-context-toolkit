#!/usr/bin/env python3
"""Read exact facts or search local knowledge packs without a server."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
from onec_help.runtime_db import ensure_sqlite_db  # noqa: E402
from onec_help.workspace_manifest import (  # noqa: E402
    load_workspace_manifest,
    resolve_target_pack,
    resolve_pack_path,
)  # noqa: E402


def query_pack(
    db: Path,
    query: str,
    *,
    limit: int = 5,
    domain: str | None = None,
    version: str | None = None,
    exact: bool = False,
    detail: str = "compact",
) -> dict:
    if not query.strip() or not 1 <= limit <= 100:
        raise ValueError("Provide a non-empty query and a limit between 1 and 100")
    started = time.perf_counter()
    path, _ = ensure_sqlite_db(db)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        if con.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise ValueError(
                "Knowledge pack needs rebuilding with this toolkit (schema 2 required)"
            )
        identifier = query.strip()
        if not exact:
            chains = re.findall(r"[\w]+(?:\.[\w]+)+", identifier)
            if len(chains) == 1:
                identifier = chains[0]
        filters, params = [], []
        if domain:
            filters.append("d.domain=?")
            params.append(domain)
        else:
            filters.append("d.domain != 'api_examples'")
        if version:
            filters.append(
                "EXISTS (SELECT 1 FROM doc_versions v WHERE v.version=? AND v.doc_id=d.id)"
            )
            params.append(version)
        suffix = "".join(" AND " + f for f in filters)
        rows = con.execute(
            "SELECT d.* FROM docs d WHERE (d.name_key IN (?, ?) OR d.topic_key=?)"
            + suffix
            + " ORDER BY CASE d.domain WHEN 'api_members' THEN 0 WHEN 'api_objects' THEN 1 ELSE 2 END, d.name, d.id LIMIT ?",
            [
                identifier.casefold(),
                "глобальный контекст." + identifier.casefold(),
                identifier.casefold(),
                *params,
                limit,
            ],
        ).fetchall()
        route = "exact"
        if not rows and not exact:
            stopwords = {
                "как",
                "какой",
                "какая",
                "какие",
                "какое",
                "что",
                "это",
                "если",
                "для",
                "на",
                "в",
                "во",
                "из",
                "с",
                "со",
                "по",
                "к",
                "о",
                "об",
                "и",
                "или",
                "ли",
                "можно",
                "нужно",
                "мне",
                "при",
                "нет",
                "не",
                "его",
                "ее",
                "the",
                "a",
                "an",
                "how",
                "what",
                "is",
                "to",
                "in",
                "of",
                "can",
                "i",
            }
            tokens = list(
                dict.fromkeys(
                    token.casefold()
                    for token in re.findall(r"\w+", query, flags=re.UNICODE)
                    if token.casefold() not in stopwords
                )
            )
            # Prefix terms cover inflection and compound API names without an embedding service.
            terms = []
            for token in tokens[:24]:
                if re.fullmatch(r"[а-яё]+", token) and len(token) > 5:
                    token = re.sub(
                        r"(?:иями|ами|ями|ого|ему|ому|ией|ие|ия|ий|ой|ей|ов|ах|ях|е|у|а|ы)$",
                        "",
                        token,
                    )
                terms.append('"' + token + '"*')
            if terms:
                fts = " OR ".join(terms)
                rows = con.execute(
                    "SELECT d.* FROM docs_fts JOIN docs d ON d.id=docs_fts.rowid "
                    "WHERE docs_fts MATCH ?"
                    + suffix
                    + " ORDER BY bm25(docs_fts, 5.0, 1.0), d.id LIMIT ?",
                    [fts, *params, limit],
                ).fetchall()
            route = "search"
        results = []
        compact_fields = (
            "syntax",
            "signature",
            "params",
            "returns",
            "availability",
            "restrictions",
            "exceptions",
            "owner_name",
            "kind",
        )
        for row in rows:
            record = json.loads(row["record_json"])
            item = {
                "domain": row["domain"],
                "name": row["name"],
                "topic_path": row["topic_path"],
                "versions": json.loads(row["versions_json"]),
                "record_id": row["id"],
            }
            if detail == "full":
                item["record"] = record
                item["text"] = row["payload"]
            else:
                item.update(
                    {key: record[key] for key in compact_fields if record.get(key)}
                )
                text = str(
                    record.get("summary")
                    or record.get("description")
                    or row["payload"]
                    or ""
                )
                item["summary"] = text[:600]
                item["summary_truncated"] = len(text) > 600
                item["more_available"] = bool(
                    set(record) - set(compact_fields) - {"summary"}
                )
            results.append(item)
    return {
        "query": query,
        "version": version,
        "route": route,
        "detail": detail,
        "results": results,
        "found": bool(results),
        "query_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group()
    source.add_argument("--db", help="Knowledge pack .db or .db.zst")
    source.add_argument("--workspace-root", help="Resolve a pack from this workspace")
    p.add_argument(
        "--role", choices=["platform", "standards", "metadata"], default="platform"
    )
    p.add_argument("--target", help="Required for ambiguous configuration targets")
    p.add_argument("--q", required=True)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--domain")
    p.add_argument("--version")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--detail", choices=["compact", "full"], default="compact")
    p.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable result including provenance",
    )
    args = p.parse_args()
    try:
        if args.workspace_root:
            root = Path(args.workspace_root).expanduser().resolve()
            value = resolve_target_pack(
                load_workspace_manifest(root), role=args.role, target=args.target
            )
            if not value:
                raise ValueError(
                    "Pack missing or target ambiguous; run ensure or specify --target"
                )
            db = resolve_pack_path(value, base_root=root)
        elif args.db:
            db = Path(args.db)
        else:
            if args.role != "platform":
                raise ValueError("Specify --workspace-root or --db for this role")
            db = REPO_ROOT / "artifacts" / "platform.kb.db.zst"
            if not db.is_file():
                raise ValueError(
                    "No bundled help. Run ensure --need platform with your HBK source, then query with --workspace-root"
                )
        result = query_pack(
            db,
            args.q,
            limit=args.limit,
            domain=args.domain,
            version=args.version,
            exact=args.exact,
            detail=args.detail,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        p.exit(2, f"onec-context: {exc}\n")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["results"]:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        if not result["found"]:
            print("No matching facts. Check the name, version, and source coverage.")
        print(f"query_ms: {result['query_ms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
