"""KD 2.0 metadata export parsing and compact snapshot helpers.

Supports XML exports produced by external data processor file and converts them into
:class:`CrawlResult` (:mod:`onec_help.knowledge.metadata_models`) for the metadata graph.

Provides compact JSONL snapshot format (`onec_kd2_snapshot_v2`, ids as `EnglishType.ObjectName`).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .metadata_ids import make_metadata_object_id
from .metadata_models import ConfigObject, CrawlResult

try:
    import defusedxml.ElementTree as _ET
except ImportError:  # pragma: no cover - optional dependency at runtime
    import xml.etree.ElementTree as _ET  # noqa: S405

ZERO_GUID = "00000000-0000-0000-0000-000000000000"

_OBJECT_TYPE_MAP: dict[str, str] = {
    "Документ": "Document",
    "Справочник": "Catalog",
    "Перечисление": "Enum",
    "РегистрСведений": "InformationRegister",
    "РегистрНакопления": "AccumulationRegister",
    "РегистрБухгалтерии": "AccountingRegister",
    "РегистрРасчета": "CalculationRegister",
    "ПланСчетов": "ChartOfAccounts",
    "ПланВидовХарактеристик": "ChartOfCharacteristicTypes",
    "ПланВидовРасчета": "ChartOfCalculationTypes",
    "ПланОбмена": "ExchangePlan",
    "БизнесПроцесс": "BusinessProcess",
    "ТочкаМаршрутаБизнесПроцесса": "RoutePoint",
    "Задача": "Task",
    # Константы: в выгрузках встречаются варианты написания типа объекта.
    "НаборКонстант": "ConstantsSet",
    "КонстантыНабор": "ConstantsSet",
    "ConstantsSet": "ConstantsSet",
    "Константа": "Constant",
    "Constant": "Constant",
}

_FIELD_KIND_TO_GROUP: dict[str, str] = {
    "Реквизит": "requisites",
    "Измерение": "dimensions",
    "Ресурс": "resources",
    "Свойство": "properties",
    # В KD2 строка с Вид=Константа — описание константы; кладём в реквизиты объекта-владельца
    # (набор или отдельная константа), как у документа, а не в отдельную группу.
    "Константа": "requisites",
    "ВидыСубконтоСчета": "properties",
    "ЭлементСоставаПланаОбмена": "properties",
    "СоставПланаОбмена": "properties",
}


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _record_from_elem(elem: Any) -> dict[str, str]:
    return {_local(child.tag): (child.text or "").strip() for child in list(elem)}


def _is_kd2_xml(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".xml":
        return False
    try:
        for _event, elem in _ET.iterparse(path, events=("start",)):  # noqa: S314
            return _local(elem.tag) == "Конфигурация"
    except Exception:
        return False
    return False


def is_kd2_snapshot_dir(path: Path) -> bool:
    return (
        path.is_dir() and (path / "manifest.json").is_file() and (path / "objects.jsonl").is_file()
    )


def is_kd2_snapshot_root(path: Path) -> bool:
    snapshots_dir = path / "snapshots"
    return (
        path.is_dir()
        and snapshots_dir.is_dir()
        and any(is_kd2_snapshot_dir(child) for child in snapshots_dir.iterdir() if child.is_dir())
    )


def list_kd2_snapshot_dirs(path: Path) -> list[Path]:
    if is_kd2_snapshot_dir(path):
        return [path.resolve()]
    snapshots_dir = path / "snapshots"
    if not snapshots_dir.is_dir():
        return []
    return [
        child.resolve()
        for child in sorted(snapshots_dir.iterdir())
        if child.is_dir() and is_kd2_snapshot_dir(child)
    ]


def _snapshot_key_from_xml(xml_path: Path) -> str:
    stem = xml_path.stem.strip().lower()
    stem = re.sub(r"[^0-9a-zа-яё_-]+", "-", stem, flags=re.IGNORECASE)
    stem = re.sub(r"-{2,}", "-", stem).strip("-_")
    return stem or "config"


def snapshot_dir_for_xml(base_dir: str | Path, xml_path: str | Path) -> Path:
    base = Path(base_dir).expanduser().resolve()
    xml = Path(xml_path).expanduser().resolve()
    return base / "snapshots" / _snapshot_key_from_xml(xml)


def find_kd2_xml_exports(path: Path) -> list[Path]:
    """Return KD2 XML exports found directly in a directory, sorted by name."""
    if not path.is_dir():
        return []
    out: list[Path] = []
    for candidate in sorted(path.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() == ".xml" and _is_kd2_xml(candidate):
            out.append(candidate.resolve())
    return out


def pick_primary_kd2_xml_export(path: Path) -> Path | None:
    """Pick the newest KD2 XML export from a directory."""
    exports = find_kd2_xml_exports(path)
    if not exports:
        return None
    return max(exports, key=lambda item: item.stat().st_mtime)


def crawl_kd2_xml_exports(paths: list[str | Path]) -> CrawlResult:
    """Parse and merge multiple KD2 XML exports into one CrawlResult."""
    crawls = [crawl_kd2_xml(path) for path in paths]
    if not crawls:
        raise FileNotFoundError("No KD2 XML exports provided")
    if len(crawls) == 1:
        return crawls[0]
    all_objects: list[ConfigObject] = []
    all_relations = []
    config_labels: list[str] = []
    for crawl in crawls:
        all_objects.extend(crawl.objects)
        all_relations.extend(crawl.relations)
        label = f"{crawl.config_name} ({crawl.config_version})".strip()
        if label and label not in config_labels:
            config_labels.append(label)
    root_dir = crawls[0].root_dir.parent if crawls[0].root_dir.is_file() else crawls[0].root_dir
    return CrawlResult(
        root_dir=root_dir,
        config_name=", ".join(config_labels[:3]) + ("…" if len(config_labels) > 3 else ""),
        config_version="multiple",
        platform_version=None,
        objects=all_objects,
        relations=all_relations,
    )


def merge_kd2_crawls(crawls: list[CrawlResult]) -> CrawlResult:
    if not crawls:
        raise FileNotFoundError("No KD2 crawls provided")
    if len(crawls) == 1:
        return crawls[0]
    all_objects: list[ConfigObject] = []
    all_relations = []
    config_labels: list[str] = []
    for crawl in crawls:
        all_objects.extend(crawl.objects)
        all_relations.extend(crawl.relations)
        label = f"{crawl.config_name} ({crawl.config_version})".strip()
        if label and label not in config_labels:
            config_labels.append(label)
    root_dir = crawls[0].root_dir.parent if crawls[0].root_dir.is_file() else crawls[0].root_dir
    return CrawlResult(
        root_dir=root_dir,
        config_name=", ".join(config_labels[:3]) + ("…" if len(config_labels) > 3 else ""),
        config_version="multiple",
        platform_version=None,
        objects=all_objects,
        relations=all_relations,
    )


def _normalize_object_name(record: dict[str, str]) -> str:
    return (record.get("Имя") or record.get("Description") or "").strip()


def _field_from_property(
    record: dict[str, str],
    *,
    resolved_types: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": (record.get("Имя") or record.get("Description") or "").strip(),
        "synonym": record.get("Синоним", "").strip(),
        "comment": record.get("Комментарий", "").strip(),
        "kind": record.get("Вид", "").strip(),
        "usage": record.get("Использование", "").strip(),
        "indexing": record.get("Индексирование", "").strip().lower() in {"true", "1", "yes"},
        "type": resolved_types[0] if resolved_types else "",
        "types": resolved_types,
    }
    try:
        length = int(record.get("КвалификаторыСтроки_Длина", "").strip() or "0")
    except ValueError:
        length = 0
    if length > 0:
        out["length"] = length
    try:
        precision = int(record.get("КвалификаторыЧисла_Точность", "").strip() or "0")
        scale = int(record.get("КвалификаторыЧисла_Длина", "").strip() or "0")
    except ValueError:
        precision = 0
        scale = 0
    if scale > 0 or precision > 0:
        out["precision"] = [scale, precision]
    defined_type = record.get("ТипыСтрокой", "").strip()
    if defined_type:
        out["defined_type"] = defined_type
    return out


def _constant_bsl_hint_text(constant_name: str) -> str:
    """Глобальный контекст 1С: ``Константы.<Имя>.Получить()`` / ``Установить()`` (набор в KD — группировка, не префикс в коде)."""
    return (
        f"Константы.{constant_name}.Получить() — значение; "
        f"Константы.{constant_name}.Установить(Значение) — только там, где разрешено (часто сервер)"
    )


def _enrich_constant_bsl_hint(field: dict[str, Any], owner: ConfigObject) -> None:
    """Подсказка по доступу к значению константы в BSL (имя из строки выгрузки / объекта)."""
    if owner.object_type == "Constant":
        cname = (owner.name or "").strip()
    else:
        cname = (field.get("name") or "").strip()
    if not cname:
        return
    field["constant_bsl_hint"] = _constant_bsl_hint_text(cname)


def _resolve_types(elem: Any, ref_index: dict[str, dict[str, str]]) -> list[str]:
    values: list[str] = []
    for child in list(elem):
        if _local(child.tag) != "Типы":
            continue
        for row in list(child):
            for sub in list(row):
                if _local(sub.tag) != "Тип":
                    continue
                raw = (sub.text or "").strip()
                if not raw:
                    continue
                info = ref_index.get(raw)
                resolved = (info or {}).get("name") or raw
                if resolved not in values:
                    values.append(resolved)
        break
    return values


def crawl_kd2_xml(path: str | Path) -> CrawlResult:
    """Parse KD2 XML export into CrawlResult for metadata indexing."""
    xml_path = Path(path).expanduser().resolve()
    if not _is_kd2_xml(xml_path):
        raise FileNotFoundError(f"KD2 XML export not found or invalid: {xml_path}")

    ref_index: dict[str, dict[str, str]] = {}
    root_name = ""
    config_name = ""
    config_version = ""

    for _event, elem in _ET.iterparse(xml_path, events=("end",)):  # noqa: S314
        tag = _local(elem.tag)
        if tag == "Конфигурация":
            root_name = (elem.attrib.get("Имя") or "").strip()
        if not tag.startswith("CatalogObject."):
            continue
        record = _record_from_elem(elem)
        ref = record.get("Ref", "").strip()
        if ref:
            ref_index[ref] = {
                "record_type": tag,
                "name": _normalize_object_name(record) or record.get("Синоним", "").strip(),
                "kind": (record.get("Тип") or record.get("Вид") or "").strip(),
            }
        if tag == "CatalogObject.Конфигурации":
            config_name = _normalize_object_name(record) or root_name
            config_version = record.get("Версия", "").strip()
        elem.clear()

    objects_by_ref: dict[str, ConfigObject] = {}
    table_sections: dict[str, tuple[str, dict[str, Any]]] = {}
    values_by_owner: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for _event, elem in _ET.iterparse(xml_path, events=("end",)):  # noqa: S314
        tag = _local(elem.tag)
        if not tag.startswith("CatalogObject."):
            continue
        record = _record_from_elem(elem)

        if tag == "CatalogObject.Объекты":
            raw_type = (record.get("Тип") or "").strip()
            is_folder = record.get("IsFolder", "").strip().lower() == "true"
            if not raw_type or (is_folder and raw_type not in _OBJECT_TYPE_MAP):
                elem.clear()
                continue
            object_type = _OBJECT_TYPE_MAP.get(raw_type)
            if not object_type:
                elem.clear()
                continue
            ref = record.get("Ref", "").strip()
            name = _normalize_object_name(record)
            if not ref or not name:
                elem.clear()
                continue
            obj = ConfigObject(
                id=make_metadata_object_id(object_type, name),
                object_type=object_type,
                name=name,
                full_name=record.get("Синоним", "").strip() or None,
                path=None,
                attributes={
                    "comment": record.get("Комментарий", "").strip(),
                    "config_name": config_name or root_name,
                    "config_version": config_version or "0.0.0.0",
                    "raw_type": raw_type,
                    "requisites": [],
                    "tabular_sections": [],
                    "dimensions": [],
                    "resources": [],
                    "properties": [],
                    "constants": [],
                    "values": [],
                },
            )
            objects_by_ref[ref] = obj

        elif tag == "CatalogObject.Свойства":
            owner_ref = record.get("Owner", "").strip()
            owner = objects_by_ref.get(owner_ref)
            if owner is None:
                elem.clear()
                continue
            parent_ref = record.get("Parent", "").strip()
            kind = (record.get("Вид") or "").strip()
            resolved_types = _resolve_types(elem, ref_index)
            if kind == "ТабличнаяЧасть":
                section = {
                    "name": _normalize_object_name(record),
                    "synonym": record.get("Синоним", "").strip(),
                    "comment": record.get("Комментарий", "").strip(),
                    "requisites": [],
                }
                owner.attributes["tabular_sections"].append(section)
                if record.get("Ref"):
                    table_sections[record["Ref"]] = (owner_ref, section)
            else:
                field = _field_from_property(record, resolved_types=resolved_types)
                if parent_ref and parent_ref != ZERO_GUID and parent_ref in table_sections:
                    table_sections[parent_ref][1]["requisites"].append(field)
                else:
                    group = _FIELD_KIND_TO_GROUP.get(kind, "properties")
                    if owner.object_type == "ConstantsSet" and kind in (
                        "Константа",
                        "Реквизит",
                        "Свойство",
                    ):
                        _enrich_constant_bsl_hint(field, owner)
                    elif owner.object_type == "Constant" and kind in (
                        "Реквизит",
                        "Свойство",
                        "Константа",
                    ):
                        _enrich_constant_bsl_hint(field, owner)
                    owner.attributes.setdefault(group, []).append(field)

        elif tag == "CatalogObject.Значения":
            owner_ref = record.get("Owner", "").strip()
            entry = {
                "name": _normalize_object_name(record),
                "synonym": record.get("Синоним", "").strip(),
                "comment": record.get("Комментарий", "").strip(),
                "predefined": record.get("Предопределенное", "").strip().lower()
                in {"true", "1", "yes"},
            }
            if owner_ref:
                values_by_owner[owner_ref].append(entry)

        elem.clear()

    for owner_ref, values in values_by_owner.items():
        owner = objects_by_ref.get(owner_ref)
        if owner is not None:
            owner.attributes["values"] = values

    return CrawlResult(
        root_dir=xml_path,
        config_name=config_name or root_name or xml_path.stem,
        config_version=config_version or "0.0.0.0",
        platform_version=None,
        objects=list(objects_by_ref.values()),
        relations=[],
    )


def write_kd2_snapshot(crawl: CrawlResult, output_dir: str | Path) -> dict[str, Any]:
    """Write compact KD2-derived snapshot as JSONL files."""
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    objects_path = out / "objects.jsonl"
    fields_path = out / "fields.jsonl"
    manifest_path = out / "manifest.json"

    field_count = 0
    with (
        objects_path.open("w", encoding="utf-8") as objects_fp,
        fields_path.open("w", encoding="utf-8") as fields_fp,
    ):
        for obj in crawl.objects:
            payload = {
                "id": obj.id,
                "object_type": obj.object_type,
                "name": obj.name,
                "full_name": obj.full_name or "",
                "config_name": crawl.config_name,
                "config_version": crawl.config_version,
                "attributes": obj.attributes,
            }
            objects_fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            attrs = obj.attributes or {}
            for group_name in ("requisites", "dimensions", "resources", "properties", "constants"):
                for field in attrs.get(group_name) or []:
                    fields_fp.write(
                        json.dumps(
                            {
                                "object_id": obj.id,
                                "object_name": obj.name,
                                "object_type": obj.object_type,
                                "config_version": crawl.config_version,
                                "group": group_name,
                                **field,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    field_count += 1
            for section in attrs.get("tabular_sections") or []:
                fields_fp.write(
                    json.dumps(
                        {
                            "object_id": obj.id,
                            "object_name": obj.name,
                            "object_type": obj.object_type,
                            "config_version": crawl.config_version,
                            "group": "tabular_sections",
                            "name": section.get("name", ""),
                            "synonym": section.get("synonym", ""),
                            "kind": "ТабличнаяЧасть",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                field_count += 1
                for field in section.get("requisites") or []:
                    fields_fp.write(
                        json.dumps(
                            {
                                "object_id": obj.id,
                                "object_name": obj.name,
                                "object_type": obj.object_type,
                                "config_version": crawl.config_version,
                                "group": "tabular_section_requisites",
                                "tabular_section": section.get("name", ""),
                                **field,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    field_count += 1

    manifest = {
        "format": "onec_kd2_snapshot_v2",
        "config_name": crawl.config_name,
        "config_version": crawl.config_version,
        "platform_version": crawl.platform_version,
        "objects": len(crawl.objects),
        "fields": field_count,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_kd2_snapshot(snapshot_dir: str | Path) -> CrawlResult:
    """Load compact snapshot written by write_kd2_snapshot back into CrawlResult."""
    base = Path(snapshot_dir).expanduser().resolve()
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    fmt = str(manifest.get("format") or "")
    if fmt and fmt not in ("onec_kd2_snapshot_v1", "onec_kd2_snapshot_v2"):
        raise ValueError(
            f"Unsupported KD2 snapshot format {fmt!r} in {base}; "
            "expected onec_kd2_snapshot_v2 (regenerate with metadata-snapshot-build)."
        )
    objects: list[ConfigObject] = []
    with (base / "objects.jsonl").open("r", encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            item = json.loads(line)
            objects.append(
                ConfigObject(
                    id=item["id"],
                    object_type=item["object_type"],
                    name=item["name"],
                    full_name=item.get("full_name") or None,
                    path=item.get("path"),
                    attributes=item.get("attributes") or {},
                )
            )
    return CrawlResult(
        root_dir=base,
        config_name=manifest.get("config_name") or base.name,
        config_version=manifest.get("config_version") or "0.0.0.0",
        platform_version=manifest.get("platform_version"),
        objects=objects,
        relations=[],
    )


def load_kd2_snapshot_set(path: str | Path) -> CrawlResult:
    base = Path(path).expanduser().resolve()
    dirs = list_kd2_snapshot_dirs(base)
    if not dirs:
        raise FileNotFoundError(f"KD2 snapshot dir not found or invalid: {base}")
    crawls = [load_kd2_snapshot(snapshot_dir) for snapshot_dir in dirs]
    return merge_kd2_crawls(crawls)
