#!/usr/bin/env python3
"""Stream-analysis for 1C metadata XML export (KD 2.0) XML.

The script is intended for large files produced by metadata export processors
such as external data processor file. It does not load the whole XML into memory.

It answers practical questions for AI/metadata indexing:
- which record kinds are present (`CatalogObject.*`);
- which metadata object types are exported;
- which property kinds are exported;
- whether property types are self-contained or require GUID resolution;
- how many nested/tabular properties exist;
- whether the export looks sufficient for object/field lookup.

Usage:
  python scripts/analyze_metadata_xml.py /path/to/export.xml
  python scripts/analyze_metadata_xml.py /path/to/export.xml --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover - optional dependency in script runtime
    import xml.etree.ElementTree as ET  # noqa: S405

ZERO_GUID = "00000000-0000-0000-0000-000000000000"


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _record_from_elem(elem: ET.Element) -> dict[str, str]:
    return {_local(child.tag): (child.text or "").strip() for child in list(elem)}


def _top(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, count in counter.most_common(limit):
        out.append({"name": key, "count": count})
    return out


def _infer_gaps(object_types: set[str]) -> list[str]:
    wanted = {
        "CommonModule": "общие модули",
        "Form": "формы",
        "CommonForm": "общие формы",
        "Report": "отчеты",
        "DataProcessor": "обработки",
        "Subsystem": "подсистемы",
        "Command": "команды",
        "Role": "роли",
    }
    gaps: list[str] = []
    for marker, label in wanted.items():
        if marker not in object_types:
            gaps.append(label)
    return gaps


def analyze_export(path: Path) -> dict[str, Any]:
    record_counts: Counter[str] = Counter()
    object_types: Counter[str] = Counter()
    property_kinds: Counter[str] = Counter()
    object_field_names: Counter[str] = Counter()
    property_field_names: Counter[str] = Counter()
    value_field_names: Counter[str] = Counter()

    ref_index: dict[str, dict[str, str]] = {}
    object_prop_counts: Counter[str] = Counter()
    object_value_counts: Counter[str] = Counter()

    root_attrs: dict[str, str] = {}

    for _event, elem in ET.iterparse(path, events=("end",)):  # noqa: S314 - local offline analysis tool
        tag = _local(elem.tag)
        if tag == "Конфигурация":
            root_attrs = dict(elem.attrib)
        if not tag.startswith("CatalogObject."):
            continue

        record = _record_from_elem(elem)
        record_counts[tag] += 1

        if tag == "CatalogObject.Объекты":
            for name in record:
                object_field_names[name] += 1
            object_types[record.get("Тип", "")] += 1
        elif tag == "CatalogObject.Свойства":
            for name in record:
                property_field_names[name] += 1
            property_kinds[record.get("Вид", "")] += 1
        elif tag == "CatalogObject.Значения":
            for name in record:
                value_field_names[name] += 1

        ref = record.get("Ref")
        if ref:
            ref_index[ref] = {
                "record_type": tag,
                "name": record.get("Description")
                or record.get("Имя")
                or record.get("Синоним")
                or "",
                "kind": record.get("Тип") or record.get("Вид") or "",
            }

        elem.clear()

    stats: dict[str, Any] = {
        "file": str(path),
        "bytes": path.stat().st_size,
        "root": root_attrs,
        "record_counts": dict(record_counts),
        "top_object_types": _top(object_types, 30),
        "top_property_kinds": _top(property_kinds, 30),
        "fields": {
            "CatalogObject.Объекты": _top(object_field_names, 40),
            "CatalogObject.Свойства": _top(property_field_names, 40),
            "CatalogObject.Значения": _top(value_field_names, 40),
        },
        "type_resolution": {},
        "structure": {},
        "coverage": {},
    }

    type_rows = 0
    resolved_type_rows = 0
    multi_type_properties = 0
    tabular_children = 0
    non_root_properties = 0
    owner_misses = 0

    for _event, elem in ET.iterparse(path, events=("end",)):  # noqa: S314 - local offline analysis tool
        tag = _local(elem.tag)
        if not tag.startswith("CatalogObject."):
            continue

        record = _record_from_elem(elem)
        owner = record.get("Owner", "")
        parent = record.get("Parent", "")

        if tag == "CatalogObject.Свойства":
            owner_name = ""
            if owner:
                owner_info = ref_index.get(owner)
                if owner_info is None:
                    owner_misses += 1
                else:
                    owner_name = owner_info["name"]
                    object_prop_counts[owner_name] += 1
            if parent and parent != ZERO_GUID:
                non_root_properties += 1
                parent_info = ref_index.get(parent)
                if parent_info and parent_info["kind"] == "ТабличнаяЧасть":
                    tabular_children += 1

            type_values: list[str] = []
            for child in list(elem):
                if _local(child.tag) != "Типы":
                    continue
                for row in list(child):
                    for sub in list(row):
                        if _local(sub.tag) != "Тип":
                            continue
                        value = (sub.text or "").strip()
                        if value:
                            type_rows += 1
                            type_values.append(value)
                            if value in ref_index:
                                resolved_type_rows += 1
                break

            if len(type_values) > 1:
                multi_type_properties += 1

        elif tag == "CatalogObject.Значения":
            if owner:
                owner_info = ref_index.get(owner)
                if owner_info:
                    object_value_counts[owner_info["name"]] += 1

        elem.clear()

    exported_object_types = {
        name
        for name, count in object_types.items()
        if name and count > 0
    }
    missing_high_level = _infer_gaps(exported_object_types)

    stats["type_resolution"] = {
        "rows": type_rows,
        "resolved_by_guid": resolved_type_rows,
        "resolution_ratio": round(resolved_type_rows / type_rows, 6) if type_rows else 0.0,
        "multi_type_properties": multi_type_properties,
    }
    stats["structure"] = {
        "properties_with_non_root_parent": non_root_properties,
        "properties_under_tabular_sections": tabular_children,
        "owner_resolution_misses": owner_misses,
        "top_objects_by_property_count": _top(object_prop_counts, 20),
        "top_objects_by_value_count": _top(object_value_counts, 20),
    }
    stats["coverage"] = {
        "missing_high_level_metadata": missing_high_level,
        "looks_like_full_config_dump": not missing_high_level,
        "suitable_for_object_and_field_lookup": True,
        "suitable_for_forms_modules_and_ui": False,
    }
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_path", help="Path to metadata XML export (KD 2.0) XML")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text summary")
    args = parser.parse_args(argv)

    path = Path(args.xml_path).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    stats = analyze_export(path)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    print(f"File: {stats['file']}")
    print(f"Size: {stats['bytes']} bytes")
    print(f"Configuration: {stats['root'].get('Имя', '')}")
    print()
    print("Record counts:")
    for name, count in stats["record_counts"].items():
        print(f"  {name}: {count}")
    print()
    print("Top object types:")
    for item in stats["top_object_types"][:15]:
        print(f"  {item['name'] or '<empty>'}: {item['count']}")
    print()
    print("Top property kinds:")
    for item in stats["top_property_kinds"][:15]:
        print(f"  {item['name'] or '<empty>'}: {item['count']}")
    print()
    print("Type resolution:")
    tr = stats["type_resolution"]
    print(f"  type rows: {tr['rows']}")
    print(f"  resolved by GUID: {tr['resolved_by_guid']}")
    print(f"  resolution ratio: {tr['resolution_ratio']:.2%}")
    print(f"  multi-type properties: {tr['multi_type_properties']}")
    print()
    print("Structure:")
    st = stats["structure"]
    print(f"  properties with non-root parent: {st['properties_with_non_root_parent']}")
    print(f"  properties under tabular sections: {st['properties_under_tabular_sections']}")
    print(f"  owner resolution misses: {st['owner_resolution_misses']}")
    print()
    print("Coverage:")
    cov = stats["coverage"]
    print(f"  suitable_for_object_and_field_lookup: {cov['suitable_for_object_and_field_lookup']}")
    print(f"  suitable_for_forms_modules_and_ui: {cov['suitable_for_forms_modules_and_ui']}")
    if cov["missing_high_level_metadata"]:
        print("  missing high-level metadata:")
        for name in cov["missing_high_level_metadata"]:
            print(f"    - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
