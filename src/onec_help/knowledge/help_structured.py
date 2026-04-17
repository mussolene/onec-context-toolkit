"""Structured API snapshot built from unpacked 1C platform HTML help."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from ..help_core.html2md import (
    _read_html_file,
    extract_outgoing_links,
    extract_v8sh_sections,
    html_to_md_content,
    iter_unpacked_hbk_html_files,
)
from ..search_store import embedding
from ..search_store.indexer import _version_sort_key, get_collection_vector_size
from ..shared import env_config

API_OBJECTS_FILE = "api_objects.jsonl"
# Имена менеджеров <ТипМенеджер.<…>> для подсказок MCP: platform_help_manager_templates (те же строки, что object_name здесь).
API_MEMBERS_FILE = "api_members.jsonl"
API_EXAMPLES_FILE = "api_examples.jsonl"
API_LINKS_FILE = "api_links.jsonl"

API_OBJECTS_COLLECTION_NAME = "onec_help_api_objects"
API_MEMBERS_COLLECTION_NAME = "onec_help_api_members"
API_EXAMPLES_COLLECTION_NAME = "onec_help_examples"
API_LINKS_COLLECTION_NAME = "onec_help_api_links"
API_TOPICS_FILE = "api_topics.jsonl"
API_TOPICS_COLLECTION_NAME = "onec_help_topics"
_WORKFLOW_RELATIONS: tuple[tuple[str, str], ...] = (
    ("СхемаКомпоновкиДанных", "ИсточникДоступныхНастроекКомпоновкиДанных"),
    ("ИсточникДоступныхНастроекКомпоновкиДанных", "КомпоновщикНастроекКомпоновкиДанных"),
    ("КомпоновщикНастроекКомпоновкиДанных", "КомпоновщикМакетаКомпоновкиДанных"),
    ("КомпоновщикМакетаКомпоновкиДанных", "ПроцессорКомпоновкиДанных"),
    (
        "ПроцессорКомпоновкиДанных",
        "ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений",
    ),
)

# Backward-compatible alias used by callers/tests from the previous structured layer.
API_COLLECTION_NAME = API_MEMBERS_COLLECTION_NAME

_SECTION_ALIASES: dict[str, str] = {
    "Описание": "description",
    "Синтаксис": "syntax",
    "Поля": "fields",
    "Параметры": "params",
    "Возвращаемое значение": "returns",
    "Пример": "example",
    "Доступность": "availability",
    "Использование в версии": "platform_since",
    "См. также": "see_also",
    "Примечание": "note",
}
_GENERIC_BREADCRUMB = {
    "объекты",
    "типы",
    "методы",
    "свойства",
    "конструкторы",
    "события",
    "functions",
    "methods",
    "properties",
    "types",
    "events",
    "constructors",
}
_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)
_STRUCTURED_MEMBER_KINDS = {"method", "property", "event", "constructor", "function", "field"}
_STRUCTURED_OBJECT_KINDS = {
    "type",
    "manager",
    "global_context",
    "metadata_object",
    "collection",
    "enum",
}
_INLINE_SECTION_LABELS = {
    "Синтаксис:": "syntax",
    "Поля:": "fields",
    "Параметры:": "params",
    "Возвращаемое значение:": "returns",
    "Описание:": "description",
    "Описание варианта метода:": "description",
    "Доступность:": "availability",
    "Пример:": "example",
    "Примечание:": "note",
    "Использование в версии:": "platform_since",
}
_INLINE_SECTION_RE = re.compile(
    "|".join(re.escape(label) for label in sorted(_INLINE_SECTION_LABELS, key=len, reverse=True))
)

_METADATA_COLLECTION_OBJECT_TYPES: dict[str, str] = {
    "Документы": "ОбъектМетаданных: Документ",
    "Справочники": "ОбъектМетаданных: Справочник",
    "Перечисления": "ОбъектМетаданных: Перечисление",
    "Константы": "ОбъектМетаданных: Константа",
    "РегистрыСведений": "ОбъектМетаданных: РегистрСведений",
    "РегистрыНакопления": "ОбъектМетаданных: РегистрНакопления",
    "РегистрыБухгалтерии": "ОбъектМетаданных: РегистрБухгалтерии",
    "РегистрыРасчета": "ОбъектМетаданных: РегистрРасчета",
    "ПланыСчетов": "ОбъектМетаданных: ПланСчетов",
    "ПланыВидовХарактеристик": "ОбъектМетаданных: ПланВидовХарактеристик",
    "ПланыВидовРасчета": "ОбъектМетаданных: ПланВидовРасчета",
    "ПланыОбмена": "ОбъектМетаданных: ПланОбмена",
    "БизнесПроцессы": "ОбъектМетаданных: БизнесПроцесс",
    "Задачи": "ОбъектМетаданных: Задача",
    "Отчеты": "ОбъектМетаданных: Отчет",
    "Отчёты": "ОбъектМетаданных: Отчет",
    "Обработки": "ОбъектМетаданных: Обработка",
    "ХранилищаНастроек": "ОбъектМетаданных: ХранилищеНастроек",
    "КритерииОтбора": "ОбъектМетаданных: КритерийОтбора",
    "ЖурналыДокументов": "ОбъектМетаданных: ЖурналДокументов",
    "Последовательности": "ОбъектМетаданных: Последовательность",
}


def get_help_structured_dir() -> Path:
    """Derived structured help snapshot directory."""
    return Path(env_config.get_help_structured_dir()).expanduser().resolve()


def canonical_topic_path(full_path: str, version: str) -> str:
    """Strip platform version prefix from unpacked topic path (``{version}/{stem}/…`` → ``{stem}/…``)."""
    fp = (full_path or "").replace("\\", "/").strip()
    while fp.startswith("/"):
        fp = fp[1:]
    ver = (version or "").strip()
    if ver and fp.startswith(ver + "/"):
        return fp[len(ver) + 1 :]
    return fp


# Keys excluded from content-hash merge (identity / bookkeeping).
_HASH_MERGE_EXCLUDE: frozenset[str] = frozenset({"id", "version", "versions", "content_hash"})


def _stable_record_hash_for_merge(record: dict[str, Any]) -> str:
    """SHA-256 hex over canonical JSON of record minus id/version/versions/content_hash."""
    import hashlib

    def _norm(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _norm(obj[k]) for k in sorted(obj)}
        if isinstance(obj, list):
            return [_norm(x) for x in obj]
        if isinstance(obj, str):
            return _normalize_text(obj)
        return obj

    cleaned: dict[str, Any] = {}
    for k in sorted(record):
        if k in _HASH_MERGE_EXCLUDE:
            continue
        cleaned[k] = _norm(record[k])
    raw = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_version_values(rec: dict[str, Any]) -> list[str]:
    vs = rec.get("versions")
    if isinstance(vs, list) and vs:
        return [str(v).strip() for v in vs if str(v).strip()]
    v = rec.get("version")
    return [str(v).strip()] if v and str(v).strip() else []


def _merge_version_strings(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for g in groups:
        for v in g:
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    out.sort(key=lambda s: _version_sort_key(s), reverse=True)
    return out


def _merge_two_content_records(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Last write wins for fields; union versions."""
    out = dict(b)
    merged_v = _merge_version_strings(_record_version_values(a), _record_version_values(b))
    if merged_v:
        out["versions"] = merged_v
        out["version"] = merged_v[0]
    return out


def _finalize_merged_record(
    rec: dict[str, Any], content_hash: str, *, id_suffix: str
) -> dict[str, Any]:
    """Set id, content_hash, versions and representative version on a merged snapshot row."""
    import hashlib

    lang = str(rec.get("language") or "")
    versions = _merge_version_strings(_record_version_values(rec))
    out = dict(rec)
    out["content_hash"] = content_hash
    if versions:
        out["versions"] = versions
        out["version"] = versions[0]
    key = f"{id_suffix}|{lang}|{content_hash}"
    out["id"] = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:14], 16) % (2**63)
    return out


def payload_matches_platform_version(payload: dict[str, Any], version: str | None) -> bool:
    """True if payload applies to the given platform version (single or merged ``versions``)."""
    if not version or not str(version).strip():
        return True
    v = str(version).strip()
    if str(payload.get("version") or "").strip() == v:
        return True
    vers = payload.get("versions")
    if isinstance(vers, list) and v in [str(x).strip() for x in vers if x]:
        return True
    return False


def _merge_snapshot_records(
    records: list[dict[str, Any]], *, id_suffix: str
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in records:
        lang = str(rec.get("language") or "")
        h = _stable_record_hash_for_merge(rec)
        key = (lang, h)
        if key not in buckets:
            buckets[key] = rec.copy()
        else:
            buckets[key] = _merge_two_content_records(buckets[key], rec)
    ordered = sorted(buckets.keys(), key=lambda k: (k[0], k[1]))
    return [_finalize_merged_record(buckets[k], k[1], id_suffix=id_suffix) for k in ordered]


def _topic_point_id(path: str, version: str = "", language: str = "") -> int:
    import hashlib

    key = f"{version}|{language}|{path}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:14], 16) % (2**63)


def _normalize_text(value: str) -> str:
    return "\n".join(
        line.rstrip() for line in (value or "").replace("\r\n", "\n").splitlines()
    ).strip()


def _compact_summary(value: str, max_chars: int = 500) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _strip_inline_title_noise(text: str, title: str, breadcrumb: list[str] | None) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    normalized_title = _strip_title_suffix(title).lower()
    noise = {normalized_title}
    for item in breadcrumb or []:
        raw = str(item or "").strip().lower()
        if raw:
            noise.add(raw)
    cleaned = [line for line in lines if _strip_title_suffix(line).lower() not in noise]
    return _normalize_text("\n".join(cleaned))


def _strip_title_suffix(title: str) -> str:
    base = (title or "").strip()
    if " (" in base:
        base = base.split(" (", 1)[0].strip()
    return base


def _parenthetical_synonym(title: str, base: str) -> str | None:
    """English name from 'Имя (EnglishName)' for extra aliases / search."""
    t = (title or "").strip()
    if " (" not in t:
        return None
    rest = t.split(" (", 1)[1].strip().rstrip(")").strip()
    if not rest or rest.lower() == (base or "").lower():
        return None
    return rest


def _member_parent_from_breadcrumb(title: str, breadcrumb: list[str] | None) -> str:
    title_lower = (title or "").strip().lower()
    for item in reversed(breadcrumb or []):
        raw = str(item or "").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered == title_lower or lowered in _GENERIC_BREADCRUMB:
            continue
        return raw
    return ""


def _normalize_api_name(title: str, entity_type: str, breadcrumb: list[str] | None) -> str:
    base = _strip_title_suffix(title)
    if "." in base or entity_type not in {"method", "property", "event", "constructor", "field"}:
        return base
    parent = _member_parent_from_breadcrumb(base, breadcrumb)
    if not parent:
        return base
    return f"{parent}.{base}"


def _infer_member_kind(topic_path: str, title: str, entity_type: str) -> str:
    entity = (entity_type or "").strip().lower()
    if entity in _STRUCTURED_MEMBER_KINDS:
        return entity
    path = (topic_path or "").replace("\\", "/").lower()
    title_clean = (title or "").strip()
    if "/methods/" in path:
        if "/script functions/" in path or title_clean.startswith("Встроенные функции языка."):
            return "function"
        return "method"
    if "/tables/" in path and "/fields/" in path:
        return "field"
    if "/properties/" in path:
        return "property"
    if "/events/" in path:
        return "event"
    if "/ctors/" in path or ".По умолчанию" in title_clean:
        return "constructor"
    return "topic"


# HBK labels that contain language/syntax operator topics (not context API).
# Derived from platform help layout: shlang_* = built-in language syntax,
# shclang_* = client-side language syntax, embedlang = embedded language.
_LANGUAGE_TOPIC_LABELS: frozenset[str] = frozenset({"shlang", "shclang", "embedlang"})


def _is_language_hbk(path: str, hbk_label: str = "") -> bool:
    """Return True when this topic comes from a language-syntax HBK book."""
    label = (hbk_label or "").lower().strip()
    if label:
        # Use the authoritative label from .hbk_info.json — strip lang suffix (shlang_ru → shlang)
        base = label.rsplit("_", 1)[0] if "_" in label else label
        return base in _LANGUAGE_TOPIC_LABELS
    # Fallback: infer from path (for callers that don't supply hbk_label)
    p = path.replace("\\", "/").lower()
    return (
        "/shclang_" in p
        or "/shlang_ru/" in p
        or "/embedlang" in p
        or p.startswith("shlang_")
        or p.startswith("shclang_")
        or p.startswith("embedlang")
    )


def _infer_object_kind(topic_path: str, title: str, *, hbk_label: str = "") -> str:
    path = (topic_path or "").replace("\\", "/").lower()
    title_base = _strip_title_suffix(title)
    if "/tables/" in path:
        return "table"
    # Match both canonical paths ("shquery_ru/…") and full paths ("/shquery_ru/…")
    if "/shquery_" in path or path.startswith("shquery_"):
        return "query_topic"
    if (
        "/shclang_" in path
        or "/embedlang" in path
        or "/shlang_ru/" in path
        or path.startswith("shlang_ru/")
        or path.startswith("shclang_")
        or path.startswith("embedlang")
    ):
        return "language_topic"
    if title_base.startswith("Глобальный контекст"):
        return "global_context"
    if title_base.startswith("ОбъектМетаданных:"):
        return "metadata_object"
    if "менеджер" in title_base.lower():
        return "manager"
    if path.endswith("/global context.html"):
        return "global_context"
    if "/enums/" in path or "перечислен" in title_base.lower():
        return "enum"
    if "/collections/" in path or "коллекц" in title_base.lower():
        return "collection"
    if "/objects/" in path:
        return "type"
    return "topic"


def _topic_doc_kind(topic_path: str) -> str:
    """Classify a general-docs topic by path stem: form_help | cli_help | article."""
    stem = (topic_path.replace("\\", "/").rsplit("/", 1)[-1]).lower()
    if stem.startswith("form_"):
        return "form_help"
    # zif2_*, zif3_*, zif_… in 1cv8_ru = command-line parameter articles
    if re.match(r"^zif\d*_", stem):
        return "cli_help"
    return "article"


def _has_structured_api_sections(sections: dict[str, str]) -> bool:
    return any(sections.get(key) for key in ("syntax", "params", "returns", "availability"))


def _should_index_object_topic(
    topic_path: str, title: str, sections: dict[str, str], kind: str
) -> bool:
    if kind in _STRUCTURED_OBJECT_KINDS:
        return True
    if kind in {"table", "query_topic", "language_topic"}:
        return True
    if not _has_structured_api_sections(sections):
        path = (topic_path or "").replace("\\", "/").lower()
        return "/objects/" in path and not any(
            marker in path for marker in ("/methods/", "/properties/", "/events/", "/ctors/")
        )
    path = (topic_path or "").replace("\\", "/").lower()
    title_base = _strip_title_suffix(title)
    if title_base.startswith("ОбъектМетаданных:"):
        return True
    return "/objects/" in path and not any(
        marker in path for marker in ("/methods/", "/properties/", "/events/", "/ctors/")
    )


def _split_markdown_sections(text: str) -> tuple[str, str, dict[str, str]]:
    lines = _normalize_text(text).splitlines()
    title = ""
    intro: list[str] = []
    sections: dict[str, list[str]] = {}
    current_key: str | None = None
    in_code = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        if not in_code and stripped.startswith("## "):
            heading = stripped[3:].strip()
            current_key = _SECTION_ALIASES.get(heading)
            if current_key:
                sections.setdefault(current_key, [])
            else:
                current_key = None
            continue
        if current_key:
            sections[current_key].append(line)
        elif title:
            intro.append(line)
    intro_text = _normalize_text("\n".join(intro))
    return (
        title,
        intro_text,
        {key: _normalize_text("\n".join(value)) for key, value in sections.items()},
    )


def _parse_param_lines(text: str) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    inline_matches = []
    if not any("**" in line for line in lines):
        inline_matches = list(
            re.finditer(
                r"(<[^>]+>\s*\((?:обязательный|необязательный)\).*?)(?=(<[^>]+>\s*\((?:обязательный|необязательный)\))|$)",
                " ".join(lines),
                re.IGNORECASE,
            )
        )

    if inline_matches:
        for match in inline_matches:
            chunk = " ".join(match.group(1).split())
            name_match = re.match(r"(<[^>]+>)\s*\(([^)]+)\)", chunk)
            if not name_match:
                continue
            type_match = re.search(r"Тип:\s*(.+?)(?:\s+\.\s+|\.$)", chunk)
            description = chunk
            if type_match:
                description = chunk[type_match.end() :].strip()
            params.append(
                {
                    "name": name_match.group(1).strip(),
                    "type": (type_match.group(1).strip() if type_match else "—"),
                    "description": description,
                }
            )
        if params:
            return params
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("-"):
            line = line.lstrip("- ").strip()
        if line.startswith("<") and ">" in line:
            name = line
            type_value = ""
            description = ""
            if idx + 1 < len(lines) and lines[idx + 1].startswith("Тип:"):
                type_value = lines[idx + 1].removeprefix("Тип:").strip()
                idx += 1
            if idx + 1 < len(lines):
                description = lines[idx + 1]
                idx += 1
            params.append({"name": name, "type": type_value or "—", "description": description})
        else:
            m = re.match(r"\*\*(.+?)\*\*\s+\((.+?)\)(?:\s+—\s+(.*))?$", line)
            if m:
                params.append(
                    {
                        "name": m.group(1).strip(),
                        "type": m.group(2).strip(),
                        "description": (m.group(3) or "").strip(),
                    }
                )
            elif line:
                params.append({"name": line, "type": "", "description": ""})
        idx += 1
    return params


def _extract_code_blocks(md_text: str) -> list[str]:
    return [block.strip() for block in _CODE_BLOCK_RE.findall(md_text or "") if block.strip()]


def _extract_see_also(section_text: str) -> list[str]:
    if not section_text:
        return []
    values: list[str] = []
    skip_values = {"описание", "description", "см. также", "see also"}
    for raw in section_text.splitlines():
        line = raw.strip().strip("-").strip()
        if not line:
            continue
        if line.lower() in skip_values:
            continue
        values.append(line)
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _extract_inline_sections(text: str) -> tuple[str, dict[str, str]]:
    normalized = _normalize_text(text)
    if not normalized:
        return "", {}
    matches = list(_INLINE_SECTION_RE.finditer(normalized))
    if not matches:
        return normalized, {}
    intro = normalized[: matches[0].start()].strip()
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        label = match.group(0)
        key = _INLINE_SECTION_LABELS[label]
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized)
        value = _normalize_text(normalized[start:end])
        if not value:
            continue
        if key in sections and sections[key]:
            sections[key] = f"{sections[key]}\n\n{value}"
        else:
            sections[key] = value
    return intro, sections


def _clean_syntax(text: str) -> str:
    value = _normalize_text(text)
    if value in {"```", "```\n```"}:
        return ""
    if value.startswith("```") and value.endswith("```"):
        value = _CODE_BLOCK_RE.sub(lambda m: m.group(1).strip(), value).strip()
    return value


def _clean_returns(text: str) -> str:
    value = _normalize_text(text)
    if value in {"Описание:", "Тип:"}:
        return ""
    return value


def _clean_note(text: str) -> str:
    return _normalize_text(text)


def _extract_restrictions(*parts: str) -> str:
    text = _normalize_text("\n".join(part for part in parts if part))
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    keywords = (
        "только",
        "недоступ",
        "не поддерж",
        "не использ",
        "клиент",
        "сервер",
        "интерактив",
        "внешнее соединение",
        "мобильн",
        "веб-клиент",
        "тонкий клиент",
        "толстый клиент",
    )
    matched = [line for line in lines if any(keyword in line.lower() for keyword in keywords)]
    if matched:
        return _normalize_text("\n".join(matched))
    compact = " ".join(text.split())
    return compact if len(compact) <= 400 else compact[:397].rstrip() + "..."


def _returns_from_description(description: str) -> str:
    if not description:
        return ""
    match = re.search(r"Тип:\s*(.+?)(?:\s+\.\s+|\.$)", " ".join(description.split()))
    if not match:
        return ""
    return match.group(1).strip()


def _normalize_type_token(value: str) -> str:
    token = " ".join((value or "").split())
    if not token:
        return ""
    if token.lower().startswith("тип:"):
        token = token[4:].strip()
    token = re.sub(r"\.\s*<", ".<", token)
    token = re.sub(r"<\s*", "<", token)
    token = re.sub(r"\s*>", ">", token)
    token = token.strip(" .,\n\t")
    return token.strip()


def _extract_value_types(text: str) -> list[str]:
    """Extract normalized type names from returns/description text.

    Examples:
    - ``Тип: HTTPОтвет .`` -> ``["HTTPОтвет"]``
    - ``СтандартноеХранилищеНастроекМенеджер , ХранилищеНастроекМенеджер. < Имя хранилища >``
      -> two normalized types
    """
    value = " ".join((text or "").split())
    if not value:
        return []
    explicit_type_prefix = value.lower().startswith("тип:")
    if explicit_type_prefix:
        value = value[4:].strip()
    parts = re.split(r"\s*[,;]\s*", value)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        candidate = re.split(r"\s+\.\s+", part, maxsplit=1)[0]
        candidate = _normalize_type_token(candidate)
        if not candidate:
            continue
        if not explicit_type_prefix and not _looks_like_type_name(candidate):
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _looks_like_type_name(candidate: str) -> bool:
    value = str(candidate or "").strip()
    if not value:
        return False
    if value.startswith("ОбъектМетаданных:"):
        return True
    if any(marker in value for marker in (".", "<", ">")):
        return True
    uppercase_count = sum(1 for ch in value if ch.isalpha() and ch == ch.upper())
    if uppercase_count >= 2:
        return True
    return bool(
        re.search(
            r"(Менеджер|Коллекция|Перечисления|Перечисление|ПеречислимыеСвойства|"
            r"Соответствие|Структура|Массив|ФиксированныйМассив|ТаблицаЗначений|"
            r"ДеревоЗначений|ОписаниеТипов|Запрос|Ответ|Список|Набор|Ссылка|Объект|"
            r"Команда|Форма|Результат|Процессор|Компоновщик|Схема|Хранилище|"
            r"Булево|Число|Строка|Дата|Время|УникальныйИдентификатор|Неопределено)$",
            value,
        )
    )


def _looks_like_typed_link_target(target_name: str) -> bool:
    value = str(target_name or "").strip()
    if not value:
        return False
    if len(value) > 120:
        return False
    if "\n" in value:
        return False
    if value.count(" ") >= 4:
        return False
    return _looks_like_type_name(value)


def _split_full_name(name: str) -> tuple[str, str]:
    value = (name or "").strip()
    if "." in value:
        owner, member = value.rsplit(".", 1)
        return owner.strip(), member.strip()
    return "", value


@lru_cache(maxsize=8192)
def _read_v8sh_page_title(html_path: str) -> str:
    path = Path(html_path)
    if not path.is_file():
        return ""
    raw_html = _read_html_file(path)
    if not raw_html.strip():
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    title_tag = soup.find("h1", class_="V8SH_pagetitle")
    if title_tag is None:
        return ""
    return _strip_title_suffix(title_tag.get_text(strip=True))


def _derive_table_owner_name_from_path(html_path: Path, topic_path: str) -> str:
    normalized = (topic_path or "").replace("\\", "/")
    if "/tables/" not in normalized or "/fields/" not in normalized:
        return ""
    if html_path.parent.name != "fields" or len(html_path.parents) < 3:
        return ""
    parent_base = html_path.parent.parent
    parent_html = parent_base.parent / f"{parent_base.name}.html"
    return _read_v8sh_page_title(str(parent_html))


def _extend_unique(items: list[str], *values: str) -> list[str]:
    seen = {str(item).strip().lower() for item in items if str(item).strip()}
    out = list(items)
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _infer_resolver_family(owner_or_object_name: str) -> str:
    value = (owner_or_object_name or "").strip()
    if value.startswith("Глобальный контекст."):
        value = value.split(".", 1)[1].strip()
    if value.startswith("ОбъектМетаданныхКонфигурация."):
        value = value.split(".", 1)[1].strip()
    if value == "Глобальный контекст.Метаданные" or value == "ОбъектМетаданныхКонфигурация":
        return "Метаданные"
    if value == "ПеречислимыеСвойстваОбъектовМетаданных":
        return "СвойстваОбъектов"
    if value.startswith("ОбъектМетаданных: "):
        return value.split(": ", 1)[1].strip()
    base = value.split(".", 1)[0].strip()
    if base in _METADATA_COLLECTION_OBJECT_TYPES or base in {
        "Документы",
        "Справочники",
        "Перечисления",
        "Константы",
        "РегистрыСведений",
        "РегистрыНакопления",
        "РегистрыБухгалтерии",
        "РегистрыРасчета",
        "ПланыСчетов",
        "ПланыВидовХарактеристик",
        "ПланыВидовРасчета",
        "ПланыОбмена",
        "БизнесПроцессы",
        "Задачи",
        "Отчеты",
        "Отчёты",
        "Обработки",
        "ХранилищаНастроек",
        "ЖурналыДокументов",
        "КритерииОтбора",
        "Последовательности",
    }:
        return base
    return ""


def _surface_aliases_for_member(full_name: str, owner_name: str, member_name: str) -> list[str]:
    aliases: list[str] = []
    if full_name == "Глобальный контекст.Метаданные":
        return ["Метаданные"]
    if full_name == "ОбъектМетаданныхКонфигурация.СвойстваОбъектов":
        return ["Метаданные.СвойстваОбъектов"]
    if owner_name == "ПеречислимыеСвойстваОбъектовМетаданных" and member_name:
        return [f"Метаданные.СвойстваОбъектов.{member_name}"]
    if owner_name == "ОбъектМетаданныхКонфигурация" and member_name in _METADATA_COLLECTION_OBJECT_TYPES:
        return [f"Метаданные.{member_name}"]
    if owner_name == "Глобальный контекст" and member_name:
        return [member_name]

    from .language_resolver import _SURFACE_FAMILY_SPECS

    for spec in _SURFACE_FAMILY_SPECS.values():
        placeholder_member = f"{spec.collection_manager}.{spec.collection_item_placeholder}"
        if full_name == f"Глобальный контекст.{spec.family}":
            aliases = _extend_unique(aliases, spec.family)
        elif full_name == placeholder_member:
            aliases = _extend_unique(aliases, f"{spec.family}.{spec.collection_item_placeholder}")
        elif owner_name == spec.item_manager_template and member_name:
            aliases = _extend_unique(
                aliases,
                f"{spec.family}.{spec.collection_item_placeholder}.{member_name}",
            )
    return aliases


def _surface_aliases_for_object(object_name: str) -> list[str]:
    aliases: list[str] = []
    if object_name == "ОбъектМетаданныхКонфигурация":
        return ["Метаданные"]
    if object_name == "ПеречислимыеСвойстваОбъектовМетаданных":
        return ["Метаданные.СвойстваОбъектов"]

    from .language_resolver import _SURFACE_FAMILY_SPECS

    for spec in _SURFACE_FAMILY_SPECS.values():
        if object_name == spec.collection_manager:
            aliases = _extend_unique(aliases, spec.family)
        elif object_name == spec.item_manager_template:
            aliases = _extend_unique(aliases, f"{spec.family}.{spec.collection_item_placeholder}")
    return aliases


def _typed_relations_for_member(
    record: dict[str, Any],
    *,
    version: str,
    language: str,
    topic_path: str,
) -> list[dict[str, Any]]:
    full_name = str(record.get("full_name") or "")
    owner_name = str(record.get("owner_name") or "")
    member_name = str(record.get("member_name") or "")
    relations: list[dict[str, Any]] = []
    seq = 1

    def add(target_name: str, link_kind: str, *, target_lookup: str = "object", reason: str = "") -> None:
        nonlocal seq
        target = str(target_name or "").strip()
        if not target:
            return
        if link_kind in {
            "returns_type",
            "global_property_returns_type",
            "metadata_property_returns_type",
            "metadata_enum_property_returns_system_enum",
            "metadata_collection_contains_object_type",
        } and not _looks_like_typed_link_target(target):
            return
        relations.append(
            {
                "id": _topic_point_id(f"{topic_path}#rel-{link_kind}-{seq}", version, language),
                "source_full_name": full_name,
                "target_name": target,
                "target_lookup": target_lookup,
                "source_lookup": "member",
                "link_kind": link_kind,
                "reason": reason,
                "topic_path": topic_path,
                "version": version,
                "language": language,
                "text": f"{full_name} -> {target[:200]}",
            }
        )
        seq += 1

    for type_name in record.get("value_types") or []:
        add(type_name, "returns_type", reason="normalized value type from structured help")
    for alias in record.get("surface_aliases") or []:
        add(alias, "surface_alias", target_lookup="alias", reason="canonical BSL surface-syntax alias")

    if full_name == "Глобальный контекст.Метаданные":
        add("ОбъектМетаданныхКонфигурация", "global_property_returns_type")
    elif owner_name == "ОбъектМетаданныхКонфигурация" and member_name == "СвойстваОбъектов":
        add("ПеречислимыеСвойстваОбъектовМетаданных", "metadata_property_returns_type")
    elif owner_name == "ПеречислимыеСвойстваОбъектовМетаданных":
        for type_name in record.get("value_types") or []:
            add(type_name, "metadata_enum_property_returns_system_enum")
    elif owner_name == "ОбъектМетаданныхКонфигурация" and member_name in _METADATA_COLLECTION_OBJECT_TYPES:
        add(
            _METADATA_COLLECTION_OBJECT_TYPES[member_name],
            "metadata_collection_contains_object_type",
        )
    return relations


def _typed_relations_for_object(
    record: dict[str, Any],
    *,
    version: str,
    language: str,
    topic_path: str,
) -> list[dict[str, Any]]:
    full_name = str(record.get("full_name") or record.get("object_name") or "")
    relations: list[dict[str, Any]] = []
    seq = 1

    def add(target_name: str, link_kind: str, *, target_lookup: str = "alias", reason: str = "") -> None:
        nonlocal seq
        target = str(target_name or "").strip()
        if not target:
            return
        relations.append(
            {
                "id": _topic_point_id(f"{topic_path}#objrel-{link_kind}-{seq}", version, language),
                "source_full_name": full_name,
                "target_name": target,
                "target_lookup": target_lookup,
                "source_lookup": "object",
                "link_kind": link_kind,
                "reason": reason,
                "topic_path": topic_path,
                "version": version,
                "language": language,
                "text": f"{full_name} -> {target[:200]}",
            }
        )
        seq += 1

    for alias in record.get("surface_aliases") or []:
        add(alias, "surface_alias", reason="canonical BSL surface-syntax alias")
    return relations


def _make_object_stub(
    owner_name: str,
    *,
    version: str,
    language: str,
    topic_path: str = "",
    breadcrumb: list[str] | None = None,
    owner_kind: str = "type",
) -> dict[str, Any]:
    return {
        "id": _topic_point_id(f"object:{owner_name}", version, language),
        "object_name": owner_name,
        "full_name": owner_name,
        "kind": owner_kind,
        "title": owner_name,
        "summary": "",
        "description": "",
        "notes": "",
        "restrictions": "",
        "availability": "",
        "platform_since": "",
        "page_descriptor": "",
        "value_types": [],
        "version": version,
        "language": language,
        "topic_path": topic_path,
        "breadcrumb": breadcrumb or [],
        "aliases": [],
        "surface_aliases": [],
        "resolver_family": _infer_resolver_family(owner_name),
        "resolver_kind": "stub",
        "see_also": [],
        "source_sections": {},
    }


def _build_structured_records(
    *,
    title: str,
    payload_title: str,
    intro: str,
    sections: dict[str, str],
    version: str,
    language: str,
    path: str,
    entity_type: str,
    breadcrumb: list[str],
    hbk_label: str = "",
) -> tuple[
    dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]
]:
    """Build object/member/example/link records from normalized extracted sections."""
    title = title or payload_title or path
    member_kind = _infer_member_kind(path, title, entity_type)
    object_kind = _infer_object_kind(path, title, hbk_label=hbk_label)
    if not sections:
        intro, inline_sections = _extract_inline_sections(intro)
        sections = inline_sections
    path_lower = path.replace("\\", "/").lower()
    if member_kind == "topic" and "/tables/" not in path_lower:
        has_api_shape = bool(
            sections.get("syntax") or sections.get("params") or sections.get("returns")
        )
        if has_api_shape and (
            "." in _strip_title_suffix(title) or _is_language_hbk(path_lower, hbk_label)
        ):
            # Language operator topics (shlang_*) must stay as object_record (language_topic),
            # not be reclassified as member even when they have syntax+params sections.
            if object_kind != "language_topic":
                member_kind = "method"
    intro = _strip_inline_title_noise(intro, title, breadcrumb)
    description = _normalize_text(sections.get("description") or intro)
    notes = _clean_note(sections.get("note", ""))
    restrictions = _extract_restrictions(sections.get("availability", ""), notes)
    source_sections = {
        key: _normalize_text(value) for key, value in sections.items() if _normalize_text(value)
    }
    summary_source = (
        sections.get("description")
        or intro
        or sections.get("returns")
        or sections.get("syntax")
        or title
    )
    summary = _compact_summary(summary_source, 500)
    see_also = _extract_see_also(sections.get("see_also", ""))

    object_record: dict[str, Any] | None = None
    member_record: dict[str, Any] | None = None

    if member_kind in _STRUCTURED_MEMBER_KINDS:
        full_name = _normalize_api_name(title, member_kind, breadcrumb)
        owner_name, member_name = _split_full_name(full_name)
        owner_kind = (
            _infer_object_kind(path.rsplit("/", 2)[0] if "/" in path else path, owner_name)
            if owner_name
            else _infer_object_kind(path, _strip_title_suffix(title))
        )
        alias_list: list[str] = []
        if title and title != full_name:
            alias_list.append(title)
        syn_opt = _parenthetical_synonym(title, full_name)
        if syn_opt and syn_opt not in alias_list:
            alias_list.append(syn_opt)
        member_record = {
            "id": _topic_point_id(path, version, language),
            "owner_name": owner_name,
            "owner_kind": owner_kind,
            "member_name": member_name,
            "full_name": full_name,
            "kind": member_kind,
            "title": title,
            "summary": summary,
            "description": description,
            "notes": notes,
            "restrictions": restrictions,
            "syntax": _clean_syntax(sections.get("syntax", "")),
            "params": _parse_param_lines(sections.get("params", "")),
            "returns": _clean_returns(sections.get("returns", "")),
            "value_types": [],
            "availability": sections.get("availability", ""),
            "platform_since": _normalize_text(sections.get("platform_since", "")),
            "page_descriptor": _normalize_text(sections.get("page_descriptor", "")),
            "version": version,
            "language": language,
            "topic_path": path,
            "breadcrumb": breadcrumb,
            "aliases": alias_list,
            "surface_aliases": [],
            "resolver_family": _infer_resolver_family(owner_name or full_name),
            "resolver_kind": "platform_member",
            "see_also": see_also,
            "source_sections": source_sections,
        }
        if owner_name:
            object_record = _make_object_stub(
                owner_name,
                version=version,
                language=language,
                breadcrumb=breadcrumb[:-1] if breadcrumb else [],
                owner_kind=owner_kind if owner_kind in _STRUCTURED_OBJECT_KINDS else "type",
            )
        if member_kind == "property" and not member_record["returns"]:
            member_record["returns"] = _returns_from_description(
                sections.get("description", "")
            ) or _returns_from_description(summary)
        if member_kind == "field" and not member_record["returns"]:
            member_record["returns"] = _returns_from_description(
                sections.get("description", "")
            ) or _returns_from_description(summary)
        member_record["value_types"] = _extract_value_types(
            member_record.get("returns") or member_record.get("description") or summary
        )
        member_record["surface_aliases"] = _surface_aliases_for_member(
            full_name,
            owner_name,
            member_name,
        )
        if member_kind == "property" and not member_record["syntax"]:
            member_record["syntax"] = full_name
            member_record["source_sections"] = {
                **member_record["source_sections"],
                "syntax_fallback": full_name,
            }
    elif _should_index_object_topic(
        path,
        title,
        {
            "syntax": sections.get("syntax", ""),
            "params": "1" if sections.get("params") else "",
            "returns": sections.get("returns", ""),
            "availability": sections.get("availability", ""),
        },
        object_kind,
    ):
        full_name = _strip_title_suffix(title)
        obj_aliases: list[str] = []
        if title and title != full_name:
            obj_aliases.append(title)
        syn_obj = _parenthetical_synonym(title, full_name)
        if syn_obj and syn_obj not in obj_aliases:
            obj_aliases.append(syn_obj)
        # full_name itself must be searchable via aliases (e.g. "ВызватьИсключение"
        # stripped from "ВызватьИсключение (Raise)" is not otherwise in the list)
        if full_name and full_name not in obj_aliases:
            obj_aliases.insert(0, full_name)
        object_record = {
            "id": _topic_point_id(path, version, language),
            "object_name": full_name,
            "full_name": full_name,
            "kind": object_kind
            if object_kind
            in (_STRUCTURED_OBJECT_KINDS | {"table", "query_topic", "language_topic"})
            else "type",
            "title": title,
            "summary": summary,
            "description": description,
            "notes": notes,
            "restrictions": restrictions,
            "availability": sections.get("availability", ""),
            "platform_since": _normalize_text(sections.get("platform_since", "")),
            "page_descriptor": _normalize_text(sections.get("page_descriptor", "")),
            "value_types": [],
            "version": version,
            "language": language,
            "topic_path": path,
            "breadcrumb": breadcrumb,
            "aliases": obj_aliases,
            "surface_aliases": [],
            "resolver_family": _infer_resolver_family(full_name),
            "resolver_kind": "platform_object",
            "see_also": see_also,
            "source_sections": source_sections,
        }
        syn = _clean_syntax(sections.get("syntax", ""))
        prs = _parse_param_lines(sections.get("params", ""))
        ret = _clean_returns(sections.get("returns", ""))
        if syn or prs or ret:
            object_record["syntax"] = syn
            object_record["params"] = prs
            object_record["returns"] = ret
        object_record["value_types"] = _extract_value_types(
            object_record.get("returns") or object_record.get("description") or summary
        )
        object_record["surface_aliases"] = _surface_aliases_for_object(full_name)

    examples: list[dict[str, Any]] = []
    example_section = sections.get("example", "")
    code_blocks = _extract_code_blocks(example_section)
    if code_blocks and member_record is not None:
        description = _compact_summary(_CODE_BLOCK_RE.sub("", example_section).strip(), 300)
        for idx, code in enumerate(code_blocks, 1):
            examples.append(
                {
                    "id": _topic_point_id(f"{path}#example-{idx}", version, language),
                    "owner_name": member_record.get("owner_name") or "",
                    "member_name": member_record.get("member_name") or "",
                    "full_name": member_record.get("full_name") or "",
                    "kind": member_record.get("kind") or "example",
                    "example_title": f"{title} — пример {idx}",
                    "title": f"{title} — пример {idx}",
                    "description": description,
                    "code": code,
                    "topic_path": path,
                    "version": version,
                    "language": language,
                }
            )

    links: list[dict[str, Any]] = []
    source_full_name = (
        (member_record or object_record or {}).get("full_name")
        or (member_record or object_record or {}).get("object_name")
        or ""
    )
    if source_full_name:
        for idx, target_name in enumerate(see_also, 1):
            links.append(
                {
                    "id": _topic_point_id(f"{path}#see-also-{idx}", version, language),
                    "source_full_name": source_full_name,
                    "target_name": target_name,
                    "target_lookup": "unknown",
                    "source_lookup": "member" if member_record is not None else "object",
                    "link_kind": "see_also",
                    "reason": "textual see_also section",
                    "topic_path": path,
                    "version": version,
                    "language": language,
                    "text": f"{source_full_name} -> {target_name[:200]}",
                }
            )
    if member_record is not None:
        links.extend(
            _typed_relations_for_member(
                member_record,
                version=version,
                language=language,
                topic_path=path,
            )
        )
    elif object_record is not None:
        links.extend(
            _typed_relations_for_object(
                object_record,
                version=version,
                language=language,
                topic_path=path,
            )
        )

    return object_record, member_record, examples, links


def extract_structured_records_from_topic(
    topic: dict[str, Any],
) -> tuple[
    dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]
]:
    """Extract structured object/member records, official examples and related links from indexed topic payload."""
    text = _normalize_text(str(topic.get("text") or ""))
    payload_title = str(topic.get("title") or "").strip()
    title, intro, sections = _split_markdown_sections(text)
    if not sections:
        intro, inline_sections = _extract_inline_sections(intro or text)
        sections = inline_sections
    return _build_structured_records(
        title=title,
        payload_title=payload_title,
        intro=intro,
        sections=sections,
        version=str(topic.get("version") or ""),
        language=str(topic.get("language") or ""),
        path=canonical_topic_path(str(topic.get("path") or ""), str(topic.get("version") or "")),
        entity_type=str(topic.get("entity_type") or "topic").strip() or "topic",
        breadcrumb=list(topic.get("breadcrumb") or []),
    )


def extract_structured_records_from_html_topic(
    html_path: Path,
    *,
    version: str,
    language: str,
    topic_path: str,
    title: str = "",
    breadcrumb: list[str] | None = None,
    entity_type: str = "topic",
    hbk_label: str = "",
) -> tuple[
    dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]
]:
    """Extract structured records directly from unpacked HTML help article."""
    raw_html = _read_html_file(html_path)
    if not raw_html.strip():
        return None, None, [], []
    soup = BeautifulSoup(raw_html, "html.parser")
    title_tag = soup.find("h1", class_="V8SH_pagetitle")
    page_title = title_tag.get_text(strip=True) if title_tag else title
    derived_breadcrumb = list(breadcrumb or [])
    if not derived_breadcrumb:
        parent_table = _derive_table_owner_name_from_path(html_path, topic_path)
        if parent_table:
            derived_breadcrumb = [parent_table]
    if title_tag is None:
        fallback_md = html_to_md_content(html_path)
        return extract_structured_records_from_topic(
            {
                "path": topic_path,
                "title": title,
                "text": fallback_md,
                "version": version,
                "language": language,
                "entity_type": entity_type,
                "breadcrumb": derived_breadcrumb,
            }
        )
    extracted = extract_v8sh_sections(soup)
    sections = {
        "description": extracted["description"],
        "syntax": extracted["syntax"],
        "fields": extracted.get("fields", ""),
        "params": extracted["params"],
        "returns": extracted["returns"],
        "availability": _normalize_text(extracted["availability"]),
        "platform_since": _normalize_text(extracted["version"]),
        "page_descriptor": _normalize_text(extracted.get("page_descriptor", "")),
        "example": extracted["example"],
        "see_also": extracted["see_also"],
        "note": extracted["note"],
    }
    intro_parts = []
    if not any(sections.values()):
        fallback_md = html_to_md_content(html_path)
        md_title, md_intro, md_sections = _split_markdown_sections(fallback_md)
        page_title = page_title or md_title or title
        sections = md_sections or sections
        if md_intro:
            intro_parts.append(md_intro)
    if sections["description"]:
        intro_parts.append(sections["description"])
    if sections["note"]:
        intro_parts.append(sections["note"])
    intro = _normalize_text("\n\n".join(part for part in intro_parts if part))
    return _build_structured_records(
        title=page_title,
        payload_title=title,
        intro=intro,
        sections=sections,
        version=version,
        language=language,
        path=topic_path,
        entity_type=entity_type,
        breadcrumb=derived_breadcrumb,
        hbk_label=hbk_label,
    )


def extract_api_records_from_topic(
    topic: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Backward-compatible wrapper that returns member record + examples for API topics."""
    object_record, member_record, examples, _links = extract_structured_records_from_topic(topic)
    if member_record is not None:
        return (
            {
                "id": member_record.get("id"),
                "name": member_record.get("full_name") or member_record.get("member_name") or "",
                "kind": member_record.get("kind") or "topic",
                "title": member_record.get("title") or "",
                "summary": member_record.get("summary") or "",
                "description": member_record.get("description") or "",
                "notes": member_record.get("notes") or "",
                "restrictions": member_record.get("restrictions") or "",
                "syntax": member_record.get("syntax") or "",
                "params": member_record.get("params") or [],
                "returns": member_record.get("returns") or "",
                "value_types": member_record.get("value_types") or [],
                "availability": member_record.get("availability") or "",
                "platform_since": member_record.get("platform_since") or "",
                "page_descriptor": member_record.get("page_descriptor") or "",
                "version": member_record.get("version") or "",
                "language": member_record.get("language") or "",
                "topic_path": member_record.get("topic_path") or "",
                "breadcrumb": member_record.get("breadcrumb") or [],
                "entity_type": member_record.get("kind") or "topic",
                "source_sections": member_record.get("source_sections") or {},
            },
            examples,
        )
    if object_record is not None:
        return (
            {
                "id": object_record.get("id"),
                "name": object_record.get("full_name") or object_record.get("object_name") or "",
                "kind": object_record.get("kind") or "topic",
                "title": object_record.get("title") or "",
                "summary": object_record.get("summary") or "",
                "description": object_record.get("description") or "",
                "notes": object_record.get("notes") or "",
                "restrictions": object_record.get("restrictions") or "",
                "syntax": "",
                "params": [],
                "returns": "",
                "value_types": object_record.get("value_types") or [],
                "availability": object_record.get("availability") or "",
                "platform_since": object_record.get("platform_since") or "",
                "page_descriptor": object_record.get("page_descriptor") or "",
                "version": object_record.get("version") or "",
                "language": object_record.get("language") or "",
                "topic_path": object_record.get("topic_path") or "",
                "breadcrumb": object_record.get("breadcrumb") or [],
                "entity_type": object_record.get("kind") or "topic",
                "source_sections": object_record.get("source_sections") or {},
            },
            examples,
        )
    return (
        {
            "id": _topic_point_id(
                str(topic.get("path") or ""),
                str(topic.get("version") or ""),
                str(topic.get("language") or ""),
            ),
            "name": _strip_title_suffix(str(topic.get("title") or "")),
            "kind": "topic",
            "title": str(topic.get("title") or ""),
            "summary": _compact_summary(str(topic.get("text") or ""), 500),
            "description": _compact_summary(str(topic.get("text") or ""), 1200),
            "notes": "",
            "restrictions": "",
            "syntax": "",
            "params": [],
            "returns": "",
            "availability": "",
            "platform_since": "",
            "page_descriptor": "",
            "version": topic.get("version") or "",
            "language": topic.get("language") or "",
            "topic_path": topic.get("path") or "",
            "breadcrumb": list(topic.get("breadcrumb") or []),
            "entity_type": "topic",
            "source_sections": {},
        },
        [],
    )


def iter_help_topics_from_index(
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = "onec_help",
) -> list[dict[str, Any]]:
    """Read unique topic payloads from help index, preferring latest version for duplicate paths."""
    from qdrant_client import QdrantClient

    from ..search_store.indexer import _get_default_qdrant_client, _version_sort_key

    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    if QdrantClient is None:
        return []
    client = _get_default_qdrant_client(host, port)
    if not client.collection_exists(collection):
        return []
    by_path: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        for point in batch:
            payload = getattr(point, "payload", None) or {}
            path = str(payload.get("path") or "").strip()
            if not path:
                continue
            current = {
                "path": path,
                "title": payload.get("title") or "",
                "text": payload.get("text") or "",
                "version": payload.get("version") or "",
                "language": payload.get("language") or "",
                "entity_type": payload.get("entity_type") or "topic",
                "breadcrumb": payload.get("breadcrumb") or [],
            }
            prev = by_path.get(path)
            if prev is None or _version_sort_key(str(current["version"])) > _version_sort_key(
                str(prev["version"])
            ):
                by_path[path] = current
        if next_offset is None:
            break
        offset = next_offset
    return list(by_path.values())


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def iter_help_topics_from_unpacked(*, unpacked_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read unpacked HTML help articles with TOC metadata from data/unpacked."""
    base = (unpacked_dir or Path(env_config.get_data_unpacked_dir())).expanduser().resolve()
    if not base.exists():
        return []
    topics: list[dict[str, Any]] = []
    for version_dir in sorted(
        p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")
    ):
        for stem_dir in sorted(
            p for p in version_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
        ):
            info_path = stem_dir / ".hbk_info.json"
            toc_path = stem_dir / ".toc.json"
            info: dict[str, Any] = {}
            toc_items: list[dict[str, Any]] = []
            if info_path.is_file():
                try:
                    info = json.loads(info_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    info = {}
            if toc_path.is_file():
                try:
                    toc_items = json.loads(toc_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    toc_items = []
            language = str(info.get("language") or "")
            version = str(info.get("version") or version_dir.name)
            hbk_label = str(info.get("label") or stem_dir.name)
            toc_map: dict[str, dict[str, Any]] = {}
            for item in toc_items:
                if not isinstance(item, dict):
                    continue
                rel = str(item.get("path") or "").strip()
                if not rel:
                    continue
                toc_map[rel] = item
            for html_path in iter_unpacked_hbk_html_files(stem_dir):
                try:
                    rel = "/" + str(html_path.relative_to(stem_dir)).replace("\\", "/")
                except ValueError:
                    continue
                toc_item = toc_map.get(rel, {})
                full_path = f"{version}/{stem_dir.name}{rel}"
                topics.append(
                    {
                        "html_path": html_path,
                        "stem_dir": stem_dir,
                        "path": full_path,
                        "title": str(
                            toc_item.get("title_ru") or toc_item.get("title_en") or html_path.stem
                        ),
                        "version": version,
                        "language": language,
                        "hbk_label": hbk_label,
                        "entity_type": str(toc_item.get("entity_type") or "topic"),
                        "breadcrumb": list(toc_item.get("breadcrumb") or []),
                    }
                )
    return topics


def _build_topic_record(
    html_path: Path,
    *,
    topic_path: str,
    title: str,
    version: str,
    language: str,
    breadcrumb: list[str],
    hbk_label: str,
) -> dict[str, Any] | None:
    """Build a general-documentation topic record from HTML that has no structured API sections."""
    md = html_to_md_content(html_path)
    if not md or not md.strip():
        return None

    # Extract title from first h1 line, use rest as body
    lines = md.strip().splitlines()
    doc_title = title
    body_lines_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            doc_title = line[2:].strip()
            body_lines_start = i + 1
            break
    doc_title = doc_title or title
    if not doc_title:
        return None
    body = "\n".join(lines[body_lines_start:]).strip()
    if not body:
        return None

    max_body = env_config.get_help_topic_body_max_chars()
    body_stored = body if max_body <= 0 else body[:max_body]

    summary = _compact_summary(body, 500)
    kind = _topic_doc_kind(topic_path)
    breadcrumb_text = " > ".join(str(x) for x in breadcrumb) if breadcrumb else ""
    text = "\n".join(filter(None, [doc_title, breadcrumb_text, hbk_label, summary]))
    return {
        "id": _topic_point_id(topic_path, version, language),
        "kind": kind,
        "title": doc_title,
        "summary": summary,
        "body": body_stored,
        "hbk_label": hbk_label,
        "topic_path": topic_path,
        "version": version,
        "language": language,
        "breadcrumb": breadcrumb,
        "text": text,
    }


def build_structured_api_snapshot(
    output_dir: Path | None = None,
    *,
    unpacked_dir: Path | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = "onec_help",
) -> dict[str, Any]:
    """Build structured API snapshot from unpacked HTML help.

    qdrant_host/qdrant_port/collection are kept only for backward-compatible callers and
    are ignored in the JSONL-first pipeline.
    """
    out_dir = (output_dir or get_help_structured_dir()).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    html_topics = iter_help_topics_from_unpacked(unpacked_dir=unpacked_dir)
    if not html_topics:
        source_base = (
            (unpacked_dir or Path(env_config.get_data_unpacked_dir())).expanduser().resolve()
        )
        raise RuntimeError(
            f"No unpacked HTML help topics found in {source_base}. "
            "Run ingest or unpack .hbk before build-api-structured."
        )

    objects_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    objects_raw: list[dict[str, Any]] = []
    members_raw: list[dict[str, Any]] = []
    examples_raw: list[dict[str, Any]] = []
    links_raw: list[dict[str, Any]] = []
    topics_raw: list[dict[str, Any]] = []
    html_links_raw: list[dict[str, Any]] = []
    names_by_topic_path: dict[str, str] = {}

    for topic in html_topics:
        canon = canonical_topic_path(str(topic.get("path") or ""), str(topic.get("version") or ""))
        object_record, member_record, topic_examples, topic_links = (
            extract_structured_records_from_html_topic(
                Path(topic["html_path"]),
                version=str(topic.get("version") or ""),
                language=str(topic.get("language") or ""),
                topic_path=canon,
                title=str(topic.get("title") or ""),
                breadcrumb=list(topic.get("breadcrumb") or []),
                entity_type=str(topic.get("entity_type") or "topic"),
                hbk_label=str(topic.get("hbk_label") or ""),
            )
        )
        if object_record is not None:
            topic_path = str(object_record.get("topic_path") or "")
            if topic_path:
                names_by_topic_path[topic_path] = str(
                    object_record.get("full_name") or object_record.get("object_name") or ""
                )
            if topic_path:
                key = (
                    str(object_record.get("version") or ""),
                    str(object_record.get("language") or ""),
                    topic_path,
                )
            else:
                key = (
                    str(object_record.get("version") or ""),
                    str(object_record.get("language") or ""),
                    str(object_record.get("full_name") or object_record.get("object_name") or ""),
                    "stub",
                )
            prev = objects_by_key.get(key)
            if prev is None or (not prev.get("topic_path") and object_record.get("topic_path")):
                objects_by_key[key] = object_record
        if member_record is not None:
            members_raw.append(member_record)
            member_topic_path = str(member_record.get("topic_path") or "")
            if member_topic_path:
                names_by_topic_path[member_topic_path] = str(member_record.get("full_name") or "")
        examples_raw.extend(topic_examples)
        links_raw.extend(topic_links)

        source_name = str(
            (member_record or object_record or {}).get("full_name")
            or (member_record or object_record or {}).get("object_name")
            or ""
        ).strip()
        stem_dir = topic.get("stem_dir")
        if source_name and isinstance(stem_dir, Path):
            for idx, link in enumerate(
                extract_outgoing_links(Path(topic["html_path"]), stem_dir),
                1,
            ):
                resolved_path = str(link.get("resolved_path") or "").strip()
                if not resolved_path:
                    continue
                html_links_raw.append(
                    {
                        "id": _topic_point_id(f"{canon}#html-link-{idx}", str(topic.get("version") or ""), str(topic.get("language") or "")),
                        "source_full_name": source_name,
                        "target_name": str(link.get("target_title") or link.get("link_text") or "").strip(),
                        "target_lookup": "topic_path",
                        "source_lookup": "member" if member_record is not None else "object",
                        "resolved_target_topic_path": f"{stem_dir.name}/{resolved_path}",
                        "href": str(link.get("href") or "").strip(),
                        "link_kind": "html_href",
                        "reason": "resolved HTML href link",
                        "topic_path": canon,
                        "version": str(topic.get("version") or ""),
                        "language": str(topic.get("language") or ""),
                        "text": f"{source_name} -> {str(link.get('target_title') or link.get('link_text') or resolved_path)[:200]}",
                    }
                )

        # Topics that produced no structured API record go into the general docs index.
        if object_record is None and member_record is None:
            topic_rec = _build_topic_record(
                Path(topic["html_path"]),
                topic_path=canon,
                title=str(topic.get("title") or ""),
                version=str(topic.get("version") or ""),
                language=str(topic.get("language") or ""),
                breadcrumb=list(topic.get("breadcrumb") or []),
                hbk_label=str(topic.get("hbk_label") or ""),
            )
            if topic_rec is not None:
                topics_raw.append(topic_rec)
                names_by_topic_path[str(topic_rec.get("topic_path") or "")] = str(
                    topic_rec.get("title") or ""
                )

    for obj in objects_by_key.values():
        objects_raw.append(obj)

    for link in html_links_raw:
        resolved_target = str(link.get("resolved_target_topic_path") or "").strip()
        if resolved_target and names_by_topic_path.get(resolved_target):
            link["target_name"] = names_by_topic_path[resolved_target]
            link["target_lookup"] = "topic" if resolved_target in {
                str(item.get("topic_path") or "") for item in topics_raw
            } else "structured_topic"

    object_items = _merge_snapshot_records(objects_raw, id_suffix="obj")
    members = _merge_snapshot_records(members_raw, id_suffix="mem")
    examples = _merge_snapshot_records(examples_raw, id_suffix="ex")
    links = _merge_snapshot_records(links_raw + html_links_raw, id_suffix="lnk")
    doc_topics = _merge_snapshot_records(topics_raw, id_suffix="doc")

    _write_jsonl(out_dir / API_OBJECTS_FILE, object_items)
    _write_jsonl(out_dir / API_MEMBERS_FILE, members)
    _write_jsonl(out_dir / API_EXAMPLES_FILE, examples)
    _write_jsonl(out_dir / API_LINKS_FILE, links)
    _write_jsonl(out_dir / API_TOPICS_FILE, doc_topics)

    manifest = {
        "format": "onec_help_structured_api_v6",
        "objects": len(object_items),
        "members": len(members),
        "examples": len(examples),
        "links": len(links),
        "topics": len(doc_topics),
        "source": "unpacked_html",
        "source_collection": "",
        "source_unpacked_dir": str(
            (unpacked_dir or Path(env_config.get_data_unpacked_dir())).expanduser().resolve()
        ),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def index_structured_help_snapshot(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    recreate: bool = True,
    batch_size: int = 200,
    bm25_enabled: bool | None = None,
    progress_callback=None,
) -> dict[str, int]:
    """Index the structured help snapshot into dedicated Qdrant collections."""
    from ..search_store.indexer import add_bm25_to_collection

    snapshot_base = (snapshot_dir or Path(get_help_structured_dir())).expanduser().resolve()
    total_expected = sum(
        len(loader(snapshot_base))
        for loader in (
            load_api_objects,
            load_api_members,
            load_api_examples,
            load_api_links,
            load_api_topics,
        )
    )
    inserted_by_collection: dict[str, int] = {
        API_OBJECTS_COLLECTION_NAME: 0,
        API_MEMBERS_COLLECTION_NAME: 0,
        API_EXAMPLES_COLLECTION_NAME: 0,
        API_LINKS_COLLECTION_NAME: 0,
        API_TOPICS_COLLECTION_NAME: 0,
    }

    def _on_collection_progress(collection_name: str, loaded: int, total: int) -> None:
        if not callable(progress_callback):
            return
        previous = inserted_by_collection.get(collection_name, 0)
        inserted_by_collection[collection_name] = loaded
        overall = sum(inserted_by_collection.values())
        try:
            progress_callback(
                overall,
                total_expected,
                phase="index_structured",
                collection=collection_name,
                collection_loaded=loaded,
                collection_total=total,
                collection_delta=max(0, loaded - previous),
            )
        except Exception:
            pass

    # Run all collection indexing tasks in parallel.
    # Progress tracking via _on_collection_progress works correctly with concurrent access
    # because it uses inserted_by_collection (updated under its own internal lock from the GIL).
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import as_completed as _as_completed

    _collection_tasks = [
        (API_OBJECTS_COLLECTION_NAME, index_structured_api_objects),
        (API_MEMBERS_COLLECTION_NAME, index_structured_api_members),
        (API_EXAMPLES_COLLECTION_NAME, index_structured_api_examples),
        (API_LINKS_COLLECTION_NAME, index_structured_api_links),
        (API_TOPICS_COLLECTION_NAME, index_structured_api_topics),
    ]

    with ThreadPoolExecutor(max_workers=5) as _pool:
        _futures = {
            _pool.submit(
                fn,
                snapshot_dir,
                qdrant_host=qdrant_host,
                qdrant_port=qdrant_port,
                collection=col,
                recreate=recreate,
                batch_size=batch_size,
                progress_callback=lambda loaded, total, _col=col: _on_collection_progress(
                    _col, loaded, total
                ),
            ): col
            for col, fn in _collection_tasks
        }
        errors: list[tuple[str, Exception]] = []
        for _fut in _as_completed(_futures):
            col = _futures[_fut]
            try:
                inserted_by_collection[col] = _fut.result()
            except Exception as exc:
                inserted_by_collection[col] = 0
                errors.append((col, exc))

    if errors:
        msgs = "; ".join(f"{c}: {e}" for c, e in errors)
        raise RuntimeError(f"[index_structured] {len(errors)} collection(s) failed: {msgs}")

    objects_inserted = inserted_by_collection[API_OBJECTS_COLLECTION_NAME]
    members_inserted = inserted_by_collection[API_MEMBERS_COLLECTION_NAME]
    examples_inserted = inserted_by_collection[API_EXAMPLES_COLLECTION_NAME]
    links_inserted = inserted_by_collection[API_LINKS_COLLECTION_NAME]
    topics_inserted = inserted_by_collection[API_TOPICS_COLLECTION_NAME]

    use_bm25 = env_config.get_bm25_enabled() if bm25_enabled is None else bm25_enabled
    if use_bm25:
        for collection_name, inserted in (
            (API_OBJECTS_COLLECTION_NAME, objects_inserted),
            (API_MEMBERS_COLLECTION_NAME, members_inserted),
            (API_EXAMPLES_COLLECTION_NAME, examples_inserted),
            (API_TOPICS_COLLECTION_NAME, topics_inserted),
        ):
            if inserted > 0:
                add_bm25_to_collection(
                    qdrant_host=qdrant_host or env_config.get_qdrant_host(),
                    qdrant_port=qdrant_port or env_config.get_qdrant_port(),
                    collection=collection_name,
                    batch_size=200,
                    verbose=True,
                )
    return {
        "objects": objects_inserted,
        "members": members_inserted,
        "examples": examples_inserted,
        "links": links_inserted,
        "topics": topics_inserted,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.is_file():
        return items
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line:
            items.append(json.loads(line))
    return items


def load_api_objects(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_OBJECTS_FILE)


def load_api_members(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_MEMBERS_FILE)


def load_api_examples(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_EXAMPLES_FILE)


def load_api_links(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_LINKS_FILE)


def load_api_topics(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_TOPICS_FILE)


def _record_embedding_text(item: dict[str, Any], *, kind: str) -> str:
    params = item.get("params") or []
    params_text = "\n".join(
        f"- {param.get('name', '')}: {param.get('type', '')}".strip(": ")
        for param in params
        if isinstance(param, dict)
    )
    parts = [
        item.get("full_name") or item.get("object_name") or "",
        item.get("title") or "",
        " ".join(str(x) for x in (item.get("surface_aliases") or []) if str(x).strip()),
        item.get("summary") or "",
        item.get("description") or "",
        item.get("notes") or "",
        item.get("restrictions") or "",
        item.get("syntax") or "",
        params_text,
        item.get("returns") or "",
        item.get("availability") or "",
        item.get("platform_since") or "",
        item.get("page_descriptor") or "",
        " > ".join(str(x) for x in (item.get("breadcrumb") or [])),
        kind,
    ]
    return "\n".join(part for part in parts if part).strip()


def _upsert_with_retry(client_factory, collection: str, points, *, max_attempts: int = 4) -> None:
    """Upsert points into Qdrant with retry on transient connection errors.

    ``client_factory`` is a zero-argument callable that returns a fresh
    ``QdrantClient``; a new client is created on each retry to avoid stale
    keep-alive connections that cause ``httpx.RemoteProtocolError``.
    """
    import time

    client = client_factory()
    delay = 5.0
    for attempt in range(1, max_attempts + 1):
        try:
            client.upsert(collection_name=collection, points=points)
            return
        except Exception as exc:
            msg = str(exc)
            # Detect transient connection/protocol errors that are worth retrying.
            is_transient = any(
                kw in msg
                for kw in (
                    "Server disconnected",
                    "RemoteProtocolError",
                    "Connection reset",
                    "ConnectionError",
                    "ReadError",
                    "ConnectError",
                    "TimeoutError",
                    "timed out",
                )
            )
            if not is_transient or attempt == max_attempts:
                raise
            print(
                f"[ingest] upsert transient error (attempt {attempt}/{max_attempts}): {exc!r} — retrying in {delay:.0f}s",
                file=__import__("sys").stderr,
            )
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
            # Recreate client to avoid stale keep-alive connection.
            try:
                client = client_factory()
            except Exception:
                pass  # if recreation fails, proceed with old client


def _index_records(
    items: list[dict[str, Any]],
    *,
    collection: str,
    recreate: bool,
    batch_size: int,
    qdrant_host: str | None,
    qdrant_port: int | None,
    payload_builder,
    use_dense: bool = True,
    progress_callback=None,
    indexed_fields: tuple[str, ...] = (),
) -> int:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

    if not items:
        return 0
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()

    def _make_client():
        return QdrantClient(
            host=host,
            port=port,
            timeout=env_config.get_qdrant_timeout(),
            check_compatibility=False,
        )

    client = _make_client()
    dim = 1
    if use_dense:
        existing_dim = (
            None
            if recreate
            else get_collection_vector_size(
                collection=collection, qdrant_host=host, qdrant_port=port
            )
        )
        dim = existing_dim or embedding.get_embedding_dimension()
    if recreate:
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
    elif not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
    if indexed_fields and hasattr(client, "create_payload_index"):
        for field_name in indexed_fields:
            try:
                client.create_payload_index(
                    collection_name=collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            except Exception:
                continue

    inserted = 0
    total_items = len(items)
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        payloads = [payload_builder(item) for item in batch]
        if use_dense:
            texts = [str(payload.get("text") or "") for payload in payloads]
            vectors = embedding.get_embedding_batch(texts, target_dimension=dim)
        else:
            vectors = [[0.0] for _ in payloads]
        points = []
        for item, payload, vector in zip(batch, payloads, vectors, strict=True):
            points.append(
                PointStruct(
                    id=int(
                        item.get("id")
                        or _topic_point_id(
                            payload.get("path", ""),
                            payload.get("version", ""),
                            payload.get("language", ""),
                        )
                    ),
                    vector=vector,
                    payload=payload,
                )
            )
        _upsert_with_retry(_make_client, collection, points)
        inserted += len(points)
        if callable(progress_callback):
            try:
                progress_callback(inserted, total_items)
            except Exception:
                pass
    return inserted


def index_structured_api_objects(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_OBJECTS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
    progress_callback=None,
) -> int:
    """Index structured API objects into dedicated object collection."""
    items = load_api_objects(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        progress_callback=progress_callback,
        payload_builder=lambda item: {
            "object_name": item.get("object_name") or "",
            "full_name": item.get("full_name") or item.get("object_name") or "",
            "name": item.get("full_name") or item.get("object_name") or "",
            "kind": item.get("kind") or "type",
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "description": item.get("description") or "",
            "notes": item.get("notes") or "",
            "restrictions": item.get("restrictions") or "",
            "syntax": item.get("syntax") or "",
            "params": item.get("params") or [],
            "returns": item.get("returns") or "",
            "value_types": item.get("value_types") or [],
            "availability": item.get("availability") or "",
            "platform_since": item.get("platform_since") or "",
            "page_descriptor": item.get("page_descriptor") or "",
            "version": item.get("version") or "",
            "versions": item.get("versions") or [],
            "content_hash": item.get("content_hash") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": item.get("kind") or "type",
            "breadcrumb": item.get("breadcrumb") or [],
            "see_also": item.get("see_also") or [],
            "aliases": item.get("aliases") or [],
            "surface_aliases": item.get("surface_aliases") or [],
            "resolver_family": item.get("resolver_family") or "",
            "resolver_kind": item.get("resolver_kind") or "",
            "source_sections": item.get("source_sections") or {},
            "text": _record_embedding_text(item, kind="object"),
        },
        indexed_fields=(
            "object_name",
            "full_name",
            "name",
            "language",
            "resolver_family",
        ),
    )


def index_structured_api_members(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_MEMBERS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
    progress_callback=None,
) -> int:
    """Index structured API members into dedicated member collection."""
    items = load_api_members(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        progress_callback=progress_callback,
        payload_builder=lambda item: {
            "owner_name": item.get("owner_name") or "",
            "owner_kind": item.get("owner_kind") or "type",
            "member_name": item.get("member_name") or "",
            "full_name": item.get("full_name") or "",
            "name": item.get("full_name") or "",
            "kind": item.get("kind") or "method",
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "description": item.get("description") or "",
            "notes": item.get("notes") or "",
            "restrictions": item.get("restrictions") or "",
            "syntax": item.get("syntax") or "",
            "params": item.get("params") or [],
            "returns": item.get("returns") or "",
            "value_types": item.get("value_types") or [],
            "availability": item.get("availability") or "",
            "platform_since": item.get("platform_since") or "",
            "page_descriptor": item.get("page_descriptor") or "",
            "version": item.get("version") or "",
            "versions": item.get("versions") or [],
            "content_hash": item.get("content_hash") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": item.get("kind") or "method",
            "breadcrumb": item.get("breadcrumb") or [],
            "see_also": item.get("see_also") or [],
            "aliases": item.get("aliases") or [],
            "surface_aliases": item.get("surface_aliases") or [],
            "resolver_family": item.get("resolver_family") or "",
            "resolver_kind": item.get("resolver_kind") or "",
            "source_sections": item.get("source_sections") or {},
            "text": _record_embedding_text(item, kind="member"),
        },
        indexed_fields=(
            "owner_name",
            "member_name",
            "full_name",
            "name",
            "language",
            "resolver_family",
        ),
    )


def index_structured_api_examples(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_EXAMPLES_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
    progress_callback=None,
) -> int:
    """Index official examples into dedicated example collection."""
    items = load_api_examples(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        progress_callback=progress_callback,
        payload_builder=lambda item: {
            "owner_name": item.get("owner_name") or "",
            "member_name": item.get("member_name") or "",
            "full_name": item.get("full_name") or "",
            "api_name": item.get("full_name") or "",
            "kind": item.get("kind") or "example",
            "title": item.get("title") or item.get("example_title") or "",
            "description": item.get("description") or "",
            "code": item.get("code") or "",
            "version": item.get("version") or "",
            "versions": item.get("versions") or [],
            "content_hash": item.get("content_hash") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": "example",
            "text": "\n".join(
                part
                for part in (
                    item.get("full_name") or "",
                    item.get("title") or "",
                    item.get("description") or "",
                    item.get("code") or "",
                )
                if part
            ),
        },
        use_dense=True,
        indexed_fields=("owner_name", "member_name", "full_name", "api_name", "language"),
    )


def index_structured_api_links(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_LINKS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
    progress_callback=None,
) -> int:
    """Index API links into dedicated relation collection."""
    import hashlib

    items = list(load_api_links(snapshot_dir))
    versions = sorted(
        {
            str(item.get("version") or "").strip()
            for item in items
            if str(item.get("version") or "").strip()
        },
        key=_version_sort_key,
        reverse=True,
    )
    for source_name, target_name in _WORKFLOW_RELATIONS:
        key = f"workflow|{source_name}|{target_name}"
        items.append(
            {
                "id": int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:14], 16) % (2**63),
                "source_full_name": source_name,
                "target_name": target_name,
                "link_kind": "workflow_next_step",
                "target_lookup": "object",
                "source_lookup": "object",
                "reason": "curated workflow edge",
                "version": versions[0] if versions else "",
                "versions": versions,
                "language": "ru",
                "topic_path": "",
                "text": f"{source_name} -> {target_name}",
            }
        )
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        progress_callback=progress_callback,
        payload_builder=lambda item: {
            "source_full_name": item.get("source_full_name") or "",
            "target_name": item.get("target_name") or "",
            "link_kind": item.get("link_kind") or "see_also",
            "target_lookup": item.get("target_lookup") or "",
            "source_lookup": item.get("source_lookup") or "",
            "resolved_target_topic_path": item.get("resolved_target_topic_path") or "",
            "href": item.get("href") or "",
            "reason": item.get("reason") or "",
            "version": item.get("version") or "",
            "versions": item.get("versions") or [],
            "content_hash": item.get("content_hash") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": "link",
            "text": item.get("text") or "",
        },
        use_dense=False,
        indexed_fields=("source_full_name", "target_name", "link_kind", "language"),
    )


def index_structured_api_topics(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_TOPICS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
    progress_callback=None,
) -> int:
    """Index general documentation topics into onec_help_topics collection."""
    items = load_api_topics(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        progress_callback=progress_callback,
        payload_builder=lambda item: {
            "kind": item.get("kind") or "article",
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "body": item.get("body") or "",
            "hbk_label": item.get("hbk_label") or "",
            "version": item.get("version") or "",
            "versions": item.get("versions") or [],
            "content_hash": item.get("content_hash") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "breadcrumb": item.get("breadcrumb") or [],
            "entity_type": "topic",
            "text": item.get("text") or "",
        },
    )


def search_api_topics(
    query: str,
    *,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search over general documentation topics collection."""
    from ..search_store.indexer import search_hybrid

    return search_hybrid(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=API_TOPICS_COLLECTION_NAME,
        limit=limit,
        version=version,
        language=language,
        full_payload=True,
        query_vector=query_vector,
    )


def _score_text_match(query: str, item: dict[str, Any], fields: list[str]) -> int:
    q = (query or "").strip().lower()
    if not q:
        return 0
    tokens = [token.lower() for token in re.findall(r"[А-Яа-яA-Za-z0-9_.-]+", q) if len(token) >= 2]
    haystack_parts = [str(item.get(field) or "") for field in fields]
    haystack = " ".join(haystack_parts).lower()
    primary = str(item.get(fields[0]) or "").lower() if fields else ""
    score = 0
    if q == primary:
        score += 100
    elif q in primary:
        score += 40
    for token in tokens:
        if token in haystack:
            score += 5
    return score


def _scroll_payloads(collection: str) -> list[dict[str, Any]]:
    from qdrant_client import QdrantClient

    from ..shared.qdrant_errors import is_qdrant_unreachable_error

    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()
    try:
        client = QdrantClient(host=host, port=port, check_compatibility=False)
        if not client.collection_exists(collection):
            return []
        offset = None
        items: list[dict[str, Any]] = []
        while True:
            points, next_offset = client.scroll(
                collection_name=collection,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for point in points:
                items.append(getattr(point, "payload", None) or {})
            if next_offset is None:
                break
            offset = next_offset
        return items
    except Exception as exc:
        if is_qdrant_unreachable_error(exc):
            return []
        raise


def search_official_examples(
    query: str,
    *,
    snapshot_dir: Path | None = None,
    limit: int = 5,
    version: str | None = None,
    language: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Qdrant-backed search over official examples extracted from help topics."""
    if snapshot_dir is None:
        from ..search_store.indexer import search_hybrid

        results = search_hybrid(
            query,
            limit=limit,
            version=version,
            language=language,
            collection=API_EXAMPLES_COLLECTION_NAME,
            query_vector=query_vector,
        )
        if results:
            return results
    items = (
        load_api_examples(snapshot_dir)
        if snapshot_dir is not None
        else _scroll_payloads(API_EXAMPLES_COLLECTION_NAME)
    )
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        if version and not payload_matches_platform_version(item, version):
            continue
        if language and str(item.get("language") or "") != language:
            continue
        score = _score_text_match(query, item, ["full_name", "title", "description", "code"])
        if score > 0:
            scored.append((score, item))
    scored.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("full_name") or ""),
            str(item[1].get("title") or ""),
        )
    )
    return [item for _, item in scored[:limit]]


def search_api_members(
    query: str,
    *,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search over structured API member collection."""
    from ..search_store.indexer import search_hybrid

    return search_hybrid(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=API_MEMBERS_COLLECTION_NAME,
        limit=limit,
        version=version,
        language=language,
        full_payload=True,
        query_vector=query_vector,
    )


def _scroll_exact_member_matches(
    client,
    *,
    field: str,
    value: str,
    version: str | None,
    language: str | None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    must = [FieldCondition(key=field, match=MatchValue(value=value))]
    if language:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))
    points, _ = client.scroll(
        collection_name=API_MEMBERS_COLLECTION_NAME,
        scroll_filter=Filter(must=must),
        limit=limit * 3 if version else limit,
        with_payload=True,
        with_vectors=False,
    )
    out = [getattr(point, "payload", None) or {} for point in points or []]
    if version:
        out = [p for p in out if payload_matches_platform_version(p, version)]
    return out[:limit]


def _scroll_exact_object_matches(
    client,
    *,
    field: str,
    value: str,
    version: str | None,
    language: str | None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    must = [FieldCondition(key=field, match=MatchValue(value=value))]
    if language:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))
    points, _ = client.scroll(
        collection_name=API_OBJECTS_COLLECTION_NAME,
        scroll_filter=Filter(must=must),
        limit=limit * 3 if version else limit,
        with_payload=True,
        with_vectors=False,
    )
    out = [getattr(point, "payload", None) or {} for point in points or []]
    if version:
        out = [p for p in out if payload_matches_platform_version(p, version)]
    return out[:limit]


def _member_version_sort_key(version_str: str) -> tuple[int, ...]:
    """Ascending member sort: prefer newer platform when name match ties."""
    return tuple(-p for p in _version_sort_key(version_str))


def _member_exact_sort_key(
    query: str, item: dict[str, Any]
) -> tuple[int, int, tuple[int, ...], str]:
    query_clean = (query or "").strip().lower()
    full_name = str(item.get("full_name") or item.get("name") or "").strip().lower()
    member_name = str(item.get("member_name") or "").strip().lower()
    owner_name = str(item.get("owner_name") or "").strip().lower()
    aliases_lower = [
        str(a).strip().lower()
        for a in (item.get("aliases") or [])
        if isinstance(a, str) and str(a).strip()
    ]
    surface_aliases_lower = [
        str(a).strip().lower()
        for a in (item.get("surface_aliases") or [])
        if isinstance(a, str) and str(a).strip()
    ]
    owner_priority = 0 if owner_name in {"глобальный контекст", "встроенные функции языка"} else 1
    if full_name == query_clean:
        priority = 0
    elif member_name == query_clean:
        priority = 1
    elif query_clean in aliases_lower:
        priority = 2
    elif query_clean in surface_aliases_lower:
        priority = 2
    elif full_name.endswith("." + query_clean):
        priority = 3
    else:
        priority = 4
    return (
        priority,
        owner_priority,
        _member_version_sort_key(str(item.get("version") or "")),
        str(item.get("topic_path") or ""),
    )


def _object_exact_sort_key(query: str, item: dict[str, Any]) -> tuple[int, tuple[int, ...], str]:
    query_clean = (query or "").strip().lower()
    full_name = str(item.get("full_name") or item.get("object_name") or "").strip().lower()
    object_name = str(item.get("object_name") or "").strip().lower()
    aliases_lower = [
        str(a).strip().lower()
        for a in (item.get("aliases") or [])
        if isinstance(a, str) and str(a).strip()
    ]
    surface_aliases_lower = [
        str(a).strip().lower()
        for a in (item.get("surface_aliases") or [])
        if isinstance(a, str) and str(a).strip()
    ]
    if full_name == query_clean:
        priority = 0
    elif object_name == query_clean:
        priority = 1
    elif query_clean in aliases_lower:
        priority = 2
    elif query_clean in surface_aliases_lower:
        priority = 2
    else:
        priority = 3
    return (
        priority,
        _member_version_sort_key(str(item.get("version") or "")),
        str(item.get("topic_path") or ""),
    )


def search_api_objects(
    query: str,
    *,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search over structured API object collection."""
    from ..search_store.indexer import search_hybrid

    return search_hybrid(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=API_OBJECTS_COLLECTION_NAME,
        limit=limit,
        version=version,
        language=language,
        full_payload=True,
        query_vector=query_vector,
    )


def get_api_member(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Exact lookup in structured API members (platform help index).

    No hybrid fallback: if there is no row for this name, it is not documented
    as that member in the ingested help (source of truth for syntax/API names).
    Use ``search_api_members`` from callers that need semantic/broad search.
    """
    from qdrant_client import QdrantClient

    from ..shared.qdrant_errors import is_qdrant_unreachable_error

    name_clean = (name or "").strip()
    if not name_clean:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    try:
        client = QdrantClient(host=host, port=port, check_compatibility=False)
        if not client.collection_exists(API_MEMBERS_COLLECTION_NAME):
            return []
        results: list[dict[str, Any]] = []
        try:
            for field in ("name", "full_name", "member_name", "aliases", "surface_aliases"):
                results.extend(
                    _scroll_exact_member_matches(
                        client,
                        field=field,
                        value=name_clean,
                        version=version,
                        language=language,
                    )
                )
        except Exception:
            results = []
        if results:
            dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
            for item in results:
                key = (
                    str(item.get("full_name") or ""),
                    str(item.get("content_hash") or ""),
                    str(item.get("topic_path") or ""),
                )
                dedup[key] = item
            return sorted(dedup.values(), key=lambda item: _member_exact_sort_key(name_clean, item))
        return []
    except Exception as exc:
        if is_qdrant_unreachable_error(exc):
            return []
        raise


def get_api_object(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Exact lookup on ``name`` in structured API objects (platform help index).

    No hybrid fallback; absent name means not in ingested object catalog for help.
    Use ``search_api_objects`` where broad/semantic search is intended.
    """
    from qdrant_client import QdrantClient
    from ..shared.qdrant_errors import is_qdrant_unreachable_error

    name_clean = (name or "").strip()
    if not name_clean:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    try:
        client = QdrantClient(host=host, port=port, check_compatibility=False)
        if not client.collection_exists(API_OBJECTS_COLLECTION_NAME):
            return []
        results: list[dict[str, Any]] = []
        try:
            for field in ("name", "full_name", "object_name", "aliases", "surface_aliases"):
                results.extend(
                    _scroll_exact_object_matches(
                        client,
                        field=field,
                        value=name_clean,
                        version=version,
                        language=language,
                    )
                )
        except Exception:
            results = []
        if results:
            dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
            for item in results:
                key = (
                    str(item.get("full_name") or item.get("object_name") or ""),
                    str(item.get("content_hash") or ""),
                    str(item.get("topic_path") or ""),
                )
                dedup[key] = item
            return sorted(
                dedup.values(),
                key=lambda item: _object_exact_sort_key(name_clean, item),
            )
        return []
    except Exception as exc:
        if is_qdrant_unreachable_error(exc):
            return []
        raise


def get_api_related(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Exact-first lookup of related API links by source name."""
    name_clean = (name or "").strip()
    if not name_clean:
        return []
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    from ..shared.qdrant_errors import is_qdrant_unreachable_error

    try:
        client = QdrantClient(
            host=env_config.get_qdrant_host(),
            port=env_config.get_qdrant_port(),
            check_compatibility=False,
        )
        if not client.collection_exists(API_LINKS_COLLECTION_NAME):
            return []
        must = [FieldCondition(key="source_full_name", match=MatchValue(value=name_clean))]
        if language:
            must.append(FieldCondition(key="language", match=MatchValue(value=language)))
        points, _ = client.scroll(
            collection_name=API_LINKS_COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        out = [dict(getattr(point, "payload", None) or {}) for point in points or []]
        if version:
            out = [item for item in out if payload_matches_platform_version(item, version)]
        out.sort(key=lambda item: (str(item.get("link_kind") or ""), str(item.get("target_name") or "")))
        return out
    except Exception as exc:
        if is_qdrant_unreachable_error(exc):
            return []
        raise
