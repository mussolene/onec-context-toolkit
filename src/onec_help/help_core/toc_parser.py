"""Parse PackBlock TOC text into structured chunks (source: alkoleft/hbk-viewer TocParser/Tokenizer).

Produces flat list of {path, title_ru, title_en, breadcrumb, entity_type} for payload and path_to_section.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BOM = "\ufeff"


def tokenize_toc(content: str) -> list[str]:
    """Split TOC content into tokens (braces, commas, quoted strings, numbers).
    Source: hbk-viewer Tokenizer.kt."""
    tokens: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(content):
        char = content[i]
        if char == BOM:
            i += 1
            continue
        if char == '"':
            if in_string:
                if i + 1 < len(content) and content[i + 1] == '"':
                    current.append('"')
                    i += 1
                else:
                    current.append(char)
                    tokens.append("".join(current))
                    current = []
                    in_string = False
            else:
                if current:
                    tokens.append("".join(current).strip())
                    current = []
                current.append(char)
                in_string = True
        elif in_string:
            current.append(char)
        elif char.isspace():
            if current:
                tokens.append("".join(current).strip())
                current = []
        elif char in ("{", "}", ","):
            if current:
                tokens.append("".join(current).strip())
                current = []
            tokens.append(char)
        else:
            current.append(char)
        i += 1
    if current:
        tokens.append("".join(current).strip())
    return [t for t in tokens if t and t != ","]


class _Peekable:
    def __init__(self, items: list[str]) -> None:
        self._it = iter(items)
        self._peeked: str | None = None

    def peek(self) -> str | None:
        if self._peeked is None:
            try:
                self._peeked = next(self._it)
            except StopIteration:
                pass
        return self._peeked

    def next(self) -> str | None:
        if self._peeked is not None:
            t, self._peeked = self._peeked, None
            return t
        try:
            return next(self._it)
        except StopIteration:
            return None

    def has_next(self) -> bool:
        return self.peek() is not None


def _expect(iterator: _Peekable, expected: str, ctx: str) -> None:
    t = iterator.next()
    if t != expected:
        raise ValueError(f"{ctx}: expected '{expected}', got '{t}'")


def _parse_number(iterator: _Peekable, ctx: str) -> int:
    t = iterator.next()
    if t is None:
        raise ValueError(f"{ctx}: no token")
    try:
        return int(t)
    except ValueError as e:
        raise ValueError(f"{ctx}: expected number, got '{t}'") from e


def _parse_string(iterator: _Peekable, ctx: str) -> str:
    t = iterator.next()
    if t is None or not (t.startswith('"') and t.endswith('"')):
        raise ValueError(f"{ctx}: expected quoted string, got '{t}'")
    return t[1:-1].replace('""', '"')


def _parse_name_object(iterator: _Peekable) -> tuple[str, str]:
    _expect(iterator, "{", "NameObject: expected '{'")
    lang = _parse_string(iterator, "NameObject: languageCode")
    name = _parse_string(iterator, "NameObject: name")
    _expect(iterator, "}", "NameObject: expected '}'")
    return (lang, name)


def _parse_name_container(iterator: _Peekable) -> dict[str, str]:
    """Return dict languageCode -> name (e.g. {'ru': '...', 'en': '...'})."""
    _expect(iterator, "{", "NameContainer: expected '{'")
    _parse_number(iterator, "NameContainer: number1")
    _parse_number(iterator, "NameContainer: number2")
    names: dict[str, str] = {}
    if iterator.has_next() and iterator.peek() != "}":
        lang, name = _parse_name_object(iterator)
        names[lang] = name
        if iterator.has_next() and iterator.peek() != "}":
            lang2, name2 = _parse_name_object(iterator)
            names[lang2] = name2
    _expect(iterator, "}", "NameContainer: expected '}'")
    return names


def _parse_properties_container(iterator: _Peekable) -> tuple[dict[str, str], str]:
    """Return (name_container dict, html_path)."""
    _expect(iterator, "{", "PropertiesContainer: expected '{'")
    _parse_number(iterator, "PropertiesContainer: number1")
    _parse_number(iterator, "PropertiesContainer: number2")
    name_container = _parse_name_container(iterator)
    html_path = _parse_string(iterator, "PropertiesContainer: htmlPath")
    _expect(iterator, "}", "PropertiesContainer: expected '}'")
    return (name_container, html_path)


def _parse_chunk(iterator: _Peekable) -> dict[str, Any] | None:
    if not iterator.has_next() or iterator.peek() != "{":
        return None
    _expect(iterator, "{", "Chunk: expected '{'")
    chunk_id = _parse_number(iterator, "Chunk: id")
    parent_id = _parse_number(iterator, "Chunk: parentId")
    child_count = _parse_number(iterator, "Chunk: childCount")
    for _ in range(child_count):
        _parse_number(iterator, "Chunk: childId")
    names, html_path = _parse_properties_container(iterator)
    _expect(iterator, "}", "Chunk: expected '}'")
    return {
        "id": chunk_id,
        "parent_id": parent_id,
        "html_path": html_path or "",
        "title_ru": names.get("ru", names.get("", "")),
        "title_en": names.get("en", ""),
    }


def parse_toc_content(content: str) -> list[dict[str, Any]]:
    """Parse TOC text (from PackBlock) into list of chunk dicts.
    Source: hbk-viewer TocParser.kt."""
    tokens = tokenize_toc(content)
    it = _Peekable(tokens)
    if not it.has_next() or it.peek() != "{":
        return []
    _expect(it, "{", "TableOfContent: expected '{'")
    _parse_number(it, "TableOfContent: chunkCount")
    chunks: list[dict[str, Any]] = []
    while it.has_next() and it.peek() == "{":
        c = _parse_chunk(it)
        if c:
            chunks.append(c)
    return chunks


def toc_chunks_to_flat(
    chunks: list[dict[str, Any]],
    infer_entity_type: bool = True,
) -> list[dict[str, Any]]:
    """Build flat list of {path, title_ru, title_en, breadcrumb, entity_type} with breadcrumb from parent chain."""
    by_id: dict[int, dict[str, Any]] = {c["id"]: c for c in chunks}
    for c in chunks:
        c["_breadcrumb"] = []
        p = c.get("parent_id")
        while p is not None and p in by_id:
            parent = by_id[p]
            title = parent.get("title_ru") or parent.get("title_en") or ""
            if title:
                c["_breadcrumb"].append(title)
            p = parent.get("parent_id")
        c["_breadcrumb"].reverse()

    flat: list[dict[str, Any]] = []
    for c in chunks:
        path = (c.get("html_path") or "").strip()
        if not path:
            continue
        breadcrumb = c.get("_breadcrumb", [])
        entity_type = "topic"
        if infer_entity_type and breadcrumb:
            last = (breadcrumb[-1] or "").lower()
            if "метод" in last or "method" in last:
                entity_type = "method"
            elif "свойств" in last or "propert" in last:
                entity_type = "property"
            elif "тип" in last or "type" in last:
                entity_type = "type"
        flat.append(
            {
                "path": path,
                "title_ru": c.get("title_ru") or "",
                "title_en": c.get("title_en") or "",
                "breadcrumb": breadcrumb,
                "entity_type": entity_type,
            }
        )
    return flat


def path_to_section_and_title_from_toc(
    flat: list[dict[str, Any]],
) -> tuple[dict[str, tuple[str, list[str]]], dict[str, str]]:
    """Build path_to_section (path -> (section_path, breadcrumb)) and path_to_title (path -> title) for indexer."""
    path_to_section: dict[str, tuple[str, list[str]]] = {}
    path_to_title: dict[str, str] = {}
    for item in flat:
        path = (item.get("path") or "").strip().replace("\\", "/")
        if not path:
            continue
        breadcrumb = list(item.get("breadcrumb") or [])
        section_path = "/".join(breadcrumb) if breadcrumb else path
        path_to_section[path] = (section_path, breadcrumb)
        title = (item.get("title_ru") or item.get("title_en") or "").strip()
        if title:
            path_to_title[path] = title
        path_no_ext = path
        if path_no_ext.lower().endswith(".html"):
            path_to_section[path_no_ext[:-5]] = (section_path, breadcrumb)
            if title:
                path_to_title[path_no_ext[:-5]] = title
    return path_to_section, path_to_title


def load_toc_json(path: Path) -> list[dict[str, Any]] | None:
    """Load .toc.json (flat list of path/title_ru/title_en/breadcrumb/entity_type). Returns None on error."""
    try:
        data = path.read_text(encoding="utf-8")
        out = json.loads(data)
        if isinstance(out, list):
            return out
        return None
    except (OSError, json.JSONDecodeError):
        return None


def save_toc_json(path: Path, flat: list[dict[str, Any]]) -> None:
    """Save flat TOC list to .toc.json (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(flat, ensure_ascii=False, indent=0), encoding="utf-8")
