"""Parse metadata directly from a 1C Designer XML source tree."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405

from .registry import FOLDER_TO_KIND


@dataclass
class MetaField:
    name: str
    group: str
    synonym: str = ""
    kind: str = ""
    type_info: str = ""
    defined_type: str = ""
    form_name: str = ""
    tabular_section: str = ""


@dataclass
class MetaObject:
    object_id: str
    object_type: str
    name: str
    full_name: str = ""
    path: str = ""
    attributes: dict[str, object] = field(default_factory=dict)
    fields: list[MetaField] = field(default_factory=list)


@dataclass
class ConfigSnapshot:
    source_root: Path
    source_kind: str
    config_name: str
    config_version: str
    objects: list[MetaObject]


@dataclass(frozen=True)
class ConfigSourceInfo:
    source_root: Path
    source_kind: str
    config_name: str
    config_version: str
    configuration_xml: Path
    configuration_xml_mtime_ns: int


def _strip_ns(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_child(elem: ET.Element, local_name: str) -> ET.Element | None:
    for child in elem:
        if _strip_ns(child.tag) == local_name:
            return child
    return None


def _find_child_text(elem: ET.Element, local_name: str) -> str:
    child = _find_child(elem, local_name)
    return (child.text or "").strip() if child is not None else ""


def _extract_synonym(props: ET.Element | None) -> str:
    if props is None:
        return ""
    synonym_elem = _find_child(props, "Synonym")
    if synonym_elem is None:
        return ""
    for item in synonym_elem:
        if _find_child_text(item, "lang") == "ru":
            content = _find_child(item, "content")
            if content is not None:
                return (content.text or "").strip()
    return ""


def _extract_attribute_name(elem: ET.Element) -> str:
    props = _find_child(elem, "Properties")
    return _find_child_text(props, "Name") if props is not None else ""


def _extract_type_info(elem: ET.Element) -> str:
    props = _find_child(elem, "Properties")
    if props is None:
        return ""
    type_elem = _find_child(props, "Type")
    if type_elem is None:
        return ""
    type_desc = _find_child(type_elem, "TypeDescription") or type_elem
    types_elem = _find_child(type_desc, "Types")
    if types_elem is None:
        return ""
    parts = [(item.text or "").strip() for item in types_elem if (item.text or "").strip()]
    return " | ".join(parts)


def _parse_configuration_info(config_root: Path) -> tuple[str, str, str]:
    config_xml = config_root / "Configuration.xml"
    if not config_xml.is_file():
        return config_root.name, "0.0.0.0", "configdump"
    try:
        root = ET.parse(str(config_xml)).getroot()  # noqa: S314
    except Exception:
        return config_root.name, "0.0.0.0", "configdump"
    cfg = None
    source_kind = "configdump"
    for child in root:
        local = _strip_ns(child.tag)
        if local == "Configuration":
            cfg = child
            source_kind = "configdump"
            break
        if local == "ConfigurationExtension":
            cfg = child
            source_kind = "extension"
            break
    if cfg is None:
        cfg = root
    props = _find_child(cfg, "Properties")
    name = _find_child_text(props, "Name") or config_root.name
    version = _find_child_text(props, "Version") or "0.0.0.0"
    return name, version, source_kind


def is_config_source_root(path: Path) -> bool:
    return (path / "Configuration.xml").is_file()


def find_config_roots(base: Path, *, max_depth: int = 10) -> list[Path]:
    base = base.expanduser().resolve()
    out: list[Path] = []
    if is_config_source_root(base):
        return [base]
    queue: list[tuple[Path, int]] = [(base, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth > max_depth:
            continue
        try:
            for child in sorted(current.iterdir()):
                if not child.is_dir():
                    continue
                if is_config_source_root(child):
                    out.append(child)
                else:
                    queue.append((child, depth + 1))
        except PermissionError:
            continue
    return out


def detect_config_source_kind(path: Path) -> str:
    if is_config_source_root(path):
        _name, _version, source_kind = _parse_configuration_info(path)
        return source_kind
    return "unknown"


def get_config_source_info(config_root: Path) -> ConfigSourceInfo:
    config_root = config_root.expanduser().resolve()
    config_xml = config_root / "Configuration.xml"
    config_name, config_version, source_kind = _parse_configuration_info(config_root)
    return ConfigSourceInfo(
        source_root=config_root,
        source_kind=source_kind,
        config_name=config_name,
        config_version=config_version,
        configuration_xml=config_xml,
        configuration_xml_mtime_ns=config_xml.stat().st_mtime_ns if config_xml.exists() else 0,
    )


def _field(
    *,
    name: str,
    group: str,
    synonym: str = "",
    kind: str = "",
    type_info: str = "",
    defined_type: str = "",
    form_name: str = "",
    tabular_section: str = "",
) -> MetaField:
    return MetaField(
        name=name,
        group=group,
        synonym=synonym,
        kind=kind,
        type_info=type_info,
        defined_type=defined_type or type_info,
        form_name=form_name,
        tabular_section=tabular_section,
    )


def _parse_form_xml(
    form_xml: Path,
    *,
    form_name: str,
) -> list[MetaField]:
    try:
        root = ET.parse(str(form_xml)).getroot()  # noqa: S314
    except Exception:
        return []
    fields: list[MetaField] = []
    attrs_section = None
    commands_section = None
    for child in root:
        local = _strip_ns(child.tag)
        if local == "Attributes":
            attrs_section = child
        elif local == "Commands":
            commands_section = child
    if attrs_section is not None:
        for attr in attrs_section:
            if _strip_ns(attr.tag) != "Attribute":
                continue
            attr_name = attr.get("name", "").strip()
            if attr_name:
                fields.append(
                    _field(
                        name=attr_name,
                        group="form_attributes",
                        kind="РеквизитФормы",
                        type_info=f"Форма.{form_name}",
                        form_name=form_name,
                    )
                )
    if commands_section is not None:
        for cmd in commands_section:
            if _strip_ns(cmd.tag) != "Command":
                continue
            cmd_name = cmd.get("name", "").strip()
            if cmd_name:
                fields.append(
                    _field(
                        name=cmd_name,
                        group="form_commands",
                        kind="КомандаФормы",
                        type_info=f"Форма.{form_name}",
                        form_name=form_name,
                    )
                )
    return fields


def _parse_object_xml(xml_path: Path, kind: str, object_name: str) -> MetaObject:
    obj = MetaObject(
        object_id=f"{kind}.{object_name}",
        object_type=kind,
        name=object_name,
        path=f"{kind}.{object_name}",
    )
    try:
        root = ET.parse(str(xml_path)).getroot()  # noqa: S314
    except Exception:
        return obj

    obj_elem = None
    for child in root:
        if _strip_ns(child.tag) == kind:
            obj_elem = child
            break
    if obj_elem is None:
        obj_elem = root

    props = _find_child(obj_elem, "Properties")
    obj.full_name = _extract_synonym(props)
    obj.attributes = {
        "comment": _find_child_text(props, "Comment") if props is not None else "",
    }
    child_objects = _find_child(obj_elem, "ChildObjects")
    if child_objects is None:
        return obj

    group_by_tag = {
        "Attribute": "requisites",
        "Dimension": "dimensions",
        "Resource": "resources",
        "AccountingFlag": "properties",
        "ExtDimensionAccountingFlag": "properties",
        "EnumValue": "values",
    }

    for child in child_objects:
        local = _strip_ns(child.tag)
        if local == "TabularSection":
            ts_name = _extract_attribute_name(child)
            ts_props = _find_child(child, "Properties")
            ts_synonym = _extract_synonym(ts_props)
            if ts_name:
                obj.fields.append(
                    _field(
                        name=ts_name,
                        group="tabular_sections",
                        synonym=ts_synonym,
                        kind="ТабличнаяЧасть",
                    )
                )
                ts_child_objects = _find_child(child, "ChildObjects")
                if ts_child_objects is not None:
                    for ts_child in ts_child_objects:
                        if _strip_ns(ts_child.tag) != "Attribute":
                            continue
                        field_name = _extract_attribute_name(ts_child)
                        if not field_name:
                            continue
                        field_props = _find_child(ts_child, "Properties")
                        obj.fields.append(
                            _field(
                                name=field_name,
                                group="tabular_section_requisites",
                                synonym=_extract_synonym(field_props),
                                kind="Реквизит",
                                type_info=_extract_type_info(ts_child),
                                tabular_section=ts_name,
                            )
                        )
            continue

        group_name = group_by_tag.get(local)
        if group_name is None:
            continue
        field_name = _extract_attribute_name(child)
        if not field_name:
            continue
        field_props = _find_child(child, "Properties")
        obj.fields.append(
            _field(
                name=field_name,
                group=group_name,
                synonym=_extract_synonym(field_props),
                kind="Реквизит" if group_name != "values" else "ЗначениеПеречисления",
                type_info=_extract_type_info(child),
            )
        )

    return obj


def crawl_config_source(config_root: Path) -> ConfigSnapshot:
    info = get_config_source_info(config_root)
    objects: list[MetaObject] = []

    for folder_name, kind in FOLDER_TO_KIND.items():
        folder = info.source_root / folder_name
        if not folder.is_dir():
            continue
        for xml_file in sorted(folder.glob("*.xml")):
            object_name = xml_file.stem
            meta_object = _parse_object_xml(xml_file, kind, object_name)
            object_dir = folder / object_name
            forms_dir = object_dir / "Forms"
            if forms_dir.is_dir():
                for form_dir in sorted(forms_dir.iterdir()):
                    if not form_dir.is_dir():
                        continue
                    form_xml = form_dir / "Ext" / "Form.xml"
                    if form_xml.is_file():
                        meta_object.fields.extend(
                            _parse_form_xml(form_xml, form_name=form_dir.name)
                        )
            objects.append(meta_object)

    return ConfigSnapshot(
        source_root=info.source_root,
        source_kind=info.source_kind,
        config_name=info.config_name,
        config_version=info.config_version,
        objects=objects,
    )


def build_snapshot_from_config_source(config_root: Path, output_dir: Path) -> Path:
    snapshot = crawl_config_source(config_root)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    objects_path = output_dir / "objects.jsonl"
    fields_path = output_dir / "fields.jsonl"
    field_count = 0

    with (
        objects_path.open("w", encoding="utf-8") as objects_fp,
        fields_path.open("w", encoding="utf-8") as fields_fp,
    ):
        for obj in snapshot.objects:
            payload = {
                "id": obj.object_id,
                "object_type": obj.object_type,
                "name": obj.name,
                "full_name": obj.full_name,
                "path": obj.path,
                "config_name": snapshot.config_name,
                "config_version": snapshot.config_version,
                "source_kind": snapshot.source_kind,
                "attributes": obj.attributes,
            }
            objects_fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            for field in obj.fields:
                fields_fp.write(
                    json.dumps(
                        {
                            "object_id": obj.object_id,
                            "object_name": obj.name,
                            "object_type": obj.object_type,
                            "config_version": snapshot.config_version,
                            "group": field.group,
                            "name": field.name,
                            "synonym": field.synonym,
                            "kind": field.kind,
                            "type": field.type_info,
                            "defined_type": field.defined_type,
                            "form_name": field.form_name,
                            "tabular_section": field.tabular_section,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                field_count += 1

    manifest = {
        "format": "onec_config_snapshot_v1",
        "source_kind": snapshot.source_kind,
        "config_name": snapshot.config_name,
        "config_version": snapshot.config_version,
        "objects": len(snapshot.objects),
        "fields": field_count,
        "source_root": str(snapshot.source_root),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_dir
