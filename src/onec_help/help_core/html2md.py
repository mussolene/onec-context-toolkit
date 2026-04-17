"""Convert 1C help HTML to Markdown (one .md per article).
Supports: (1) V8SH_* schema (Syntax Helper), (2) Legacy schema (H1–H6, tables, STRONG sections).
See docs/reference/help-formats.md for formal spec."""

import html
import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


def resolve_href(current_path: Path, href: str, base_dir: Path) -> str | None:
    """Resolve relative href to a path within base_dir. Returns normalized path string or None.
    href="#" (anchor) returns None."""
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return None
    try:
        resolved = (current_path.parent / href).resolve()
        rel = resolved.relative_to(base_dir.resolve())
    except (ValueError, OSError):
        return None
    rel_str = str(rel).replace("\\", "/")
    candidates = [
        base_dir / rel_str,
        base_dir / Path(rel_str).with_suffix(".md"),
        base_dir / Path(rel_str).with_suffix(".html"),
    ]
    if not rel_str.endswith((".md", ".html", ".htm")):
        candidates.extend([base_dir / (rel_str + ".md"), base_dir / (rel_str + ".html")])
    for c in candidates:
        if c.exists() and c.is_file():
            try:
                r = c.relative_to(base_dir)
                return str(r).replace("\\", "/")
            except ValueError:
                pass
    return None


def extract_outgoing_links(html_path: Path, base_dir: Path) -> list[dict[str, Any]]:
    """Parse HTML, find all <a href>, resolve each, return [{href, resolved_path, target_title, link_text}]."""
    result: list[dict[str, Any]] = []
    try:
        text = _read_html_file(html_path)
    except Exception:
        return result
    soup = BeautifulSoup(text, "html.parser")
    current = Path(html_path)
    seen: set[tuple[str, str]] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        link_text = a.get_text(strip=True) or ""
        if not href:
            continue
        key = (href, link_text)
        if key in seen:
            continue
        seen.add(key)
        resolved = resolve_href(current, href, base_dir)
        result.append(
            {
                "href": href,
                "resolved_path": resolved,
                "target_title": link_text,
                "link_text": link_text,
            }
        )
    return result


# Regex for Markdown links [text](url)
_MD_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def extract_links_from_markdown(
    md_text: str, current_path: Path, base_dir: Path
) -> list[dict[str, Any]]:
    """Parse Markdown [text](url) links, resolve each to base_dir, return [{href, resolved_path, target_title, link_text}]."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for m in _MD_LINK_PATTERN.finditer(md_text):
        link_text = (m.group(1) or "").strip()
        href = (m.group(2) or "").strip()
        if not href:
            continue
        key = (href, link_text)
        if key in seen:
            continue
        seen.add(key)
        resolved = resolve_href(current_path, href, base_dir)
        result.append(
            {
                "href": href,
                "resolved_path": resolved,
                "target_title": link_text,
                "link_text": link_text,
            }
        )
    return result


def _normalize_md_text(s: str) -> str:
    """Replace HTML entities with Unicode and normalize composite characters for consistent search."""
    if not s:
        return s
    s = html.unescape(s)  # &nbsp; &amp; &lt; &#160; etc. → real characters
    s = unicodedata.normalize("NFC", s)  # canonical composition (é as one codepoint)
    return s


def _table_to_md(table) -> str:
    """Convert a <table> to Markdown table."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    if len(rows) >= 2:
        rows.insert(1, "|" + "|".join([" --- " for _ in rows[0].split("|")[1:-1]]) + "|")
    return "\n".join(rows) + "\n\n"


def _legacy_body_to_md(body) -> str:
    """Convert legacy article body (H1–H6, P, TABLE, STRONG) to Markdown."""
    lines = []
    for elem in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "pre"]):
        tag = elem.name.lower()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            lines.append(
                "\n" + "#" * level + " " + elem.get_text(separator=" ", strip=True) + "\n\n"
            )
        elif tag == "table":
            tbl = _table_to_md(elem)
            if tbl:
                lines.append(tbl)
        elif tag == "pre":
            lines.append("```\n" + elem.get_text(separator="\n", strip=True) + "\n```\n\n")
        elif tag == "p":
            text = elem.get_text(separator=" ", strip=True)
            if text:
                # Inline links: keep [text](url)
                for a in elem.find_all("a", href=True):
                    a.replace_with("[" + a.get_text(strip=True) + "](" + a["href"] + ")")
                text = elem.get_text(separator=" ", strip=True)
                lines.append(text + "\n\n")
    return "\n".join(lines).strip()


# Справка 1С: пробуем UTF-8, затем CP1251 (при ошибке декода UTF-8 для 1251-файлов)
_ENCODINGS_UTF8_FIRST = ("utf-8", "cp1251", "cp866", "latin-1")


# Макс. размер HTML (байты). From env_config.
def _html_max_bytes() -> int:
    from ..shared import env_config

    return env_config.get_help_html_max_bytes()


def _looks_like_utf8_mojibake(text: str) -> bool:
    """True, если текст похож на кракозябры: UTF-8 байты прочитаны как однобайтовая кодировка.
    Признак 1: много символов Р (U+0420), С (U+0421) — байты 0xD0, 0xD1 в UTF-8 русских букв.
    Признак 2: псевдографика (╨ ╤ и т.п. U+2500–U+257F) вперемешку с кириллицей."""
    if len(text) < 20:
        return False
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    if cyrillic < 10:
        return False
    # Р и С как первый байт UTF-8 русских букв
    bad = sum(1 for c in text if c in "\u0420\u0421")  # Р, С
    if (bad / cyrillic) > 0.25:
        return True
    # Псевдографика (типично при неверной кодировке) вместе с кириллицей
    box = sum(1 for c in text if "\u2500" <= c <= "\u257f")
    return box > 5 and cyrillic > 5


def _file_encodings() -> tuple[str, ...]:
    from ..shared import env_config

    order = env_config.get_help_file_encoding()
    # HELP_FILE_ENCODING=cp1251 — сначала CP1251 (если точно знаете, что все файлы в 1251)
    if order == "cp1251":
        return ("cp1251", "utf-8", "cp866", "latin-1")
    return _ENCODINGS_UTF8_FIRST


def _try_fix_mojibake(text: str, raw: bytes) -> str | None:
    """Если текст похож на кракозябры — перекодировать или перечитать raw в другой кодировке."""
    if not _looks_like_utf8_mojibake(text):
        return None
    # Случай: файл в UTF-8, но прочитан как CP1251 → перечитаем как UTF-8
    try:
        u8 = raw.decode("utf-8")
        if not _looks_like_utf8_mojibake(u8):
            return u8
    except UnicodeDecodeError:
        pass
    # Случай: строка — UTF-8 байты, прочитанные как Latin-1 (двойная кодировка)
    try:
        fixed = text.encode("latin-1").decode("utf-8")
        if not _looks_like_utf8_mojibake(fixed):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    for alt in ("cp1251", "cp866"):
        try:
            alt_text = raw.decode(alt)
            if not _looks_like_utf8_mojibake(alt_text):
                return alt_text
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def read_file_with_encoding_fallback(path: Path, encodings: tuple[str, ...] | None = None) -> str:
    """Читает файл, пробуя кодировки по порядку. При признаках кракозябр пробует альтернативу."""
    if encodings is None:
        encodings = _file_encodings()
    raw = path.read_bytes()
    for enc in encodings:
        try:
            text = raw.decode(enc)
            fixed = _try_fix_mojibake(text, raw)
            if fixed is not None:
                return fixed
            return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _read_html_file(path: Path) -> str:
    """Read file content; try utf-8, then cp1251/cp866/latin-1. Skip files over HELP_HTML_MAX_BYTES."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size > _html_max_bytes():
        print(
            f"[html2md] skip {path.name} ({size} bytes > {_html_max_bytes()}): too large",
            file=sys.stderr,
            flush=True,
        )
        return ""
    return read_file_with_encoding_fallback(path)


def _v8sh_heading_text(tag) -> str:
    return tag.get_text(separator=" ", strip=True)


def _find_v8sh_chapter(soup: BeautifulSoup, prefix: str):
    normalized_prefix = prefix.rstrip(":").strip().lower()
    for tag in soup.find_all(class_="V8SH_chapter"):
        if not getattr(tag, "get_text", None):
            continue
        heading = _v8sh_heading_text(tag).rstrip(":").strip().lower()
        if heading.startswith(normalized_prefix):
            return tag
    return None


def _iter_v8sh_chapter_nodes(chapter) -> list[Any]:
    nodes: list[Any] = []
    for sibling in chapter.next_siblings:
        if getattr(sibling, "get", None) and "V8SH_chapter" in (sibling.get("class") or []):
            break
        if getattr(sibling, "name", None) == "hr":
            break
        nodes.append(sibling)
    return nodes


def _v8sh_nodes_text(nodes: list[Any]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            text = node.strip()
        elif getattr(node, "name", None) == "br":
            text = "\n"
        elif getattr(node, "get_text", None):
            text = node.get_text(separator=" ", strip=True)
        else:
            text = str(node).strip()
        if text:
            parts.append(text)
    return _normalize_md_text("\n".join(parts)).strip()


def _extract_v8sh_page_descriptor(soup: BeautifulSoup) -> str:
    """Строка под заголовком статьи вида [method, 8.3.13] — в справке не секция, а отдельный блок."""
    title_tag = soup.find("h1", class_="V8SH_pagetitle")
    if title_tag is None:
        return ""
    chunks: list[str] = []
    for sib in title_tag.next_siblings:
        if getattr(sib, "get", None) and "V8SH_chapter" in (sib.get("class") or []):
            break
        if getattr(sib, "name", None) == "hr":
            break
        if isinstance(sib, str):
            t = sib.strip()
            if t:
                chunks.append(t)
        elif getattr(sib, "get_text", None):
            t = sib.get_text(separator=" ", strip=True)
            if t:
                chunks.append(t)
        if sum(len(x) for x in chunks) > 400:
            break
    blob = _normalize_md_text(" ".join(chunks)).strip()
    if not blob:
        return ""
    m = re.search(r"\[[^\]]{2,240}]", blob)
    return m.group(0).strip() if m else ""


def _v8sh_compact_prose(text: str) -> str:
    value = _normalize_md_text(text)
    value = re.sub(r":\s*\n\s*", ": ", value)
    value = re.sub(r"\(\s*\n\s*", "(", value)
    value = re.sub(r"\s*\n\s*\)", ")", value)
    value = re.sub(r"\n\s*-\s*", " - ", value)
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    compact: list[str] = []
    for line in lines:
        if (
            compact
            and not compact[-1].endswith((".", ":", ";", "!", "?", ","))
            and not line.startswith("-")
        ):
            compact[-1] = f"{compact[-1]} {line}".strip()
        else:
            compact.append(line)
    value = "\n".join(compact)
    value = re.sub(r"\s+\.\s*", " . ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


def _v8sh_rubric_params(nodes: list[Any]) -> list[str]:
    items: list[str] = []
    idx = 0
    while idx < len(nodes):
        node = nodes[idx]
        if not (getattr(node, "get", None) and "V8SH_rubric" in (node.get("class") or [])):
            idx += 1
            continue
        name_tag = node.find(["p", "div"]) if getattr(node, "find", None) else None
        type_tag = node.find("a") if getattr(node, "find", None) else None
        name = name_tag.get_text(strip=True) if name_tag else node.get_text(" ", strip=True)
        type_name = type_tag.get_text(strip=True) if type_tag else "—"
        desc_nodes: list[Any] = []
        look_ahead = idx + 1
        while look_ahead < len(nodes):
            next_node = nodes[look_ahead]
            if getattr(next_node, "get", None) and "V8SH_rubric" in (next_node.get("class") or []):
                break
            desc_nodes.append(next_node)
            look_ahead += 1
        description = _v8sh_nodes_text(desc_nodes)
        if type_name == "—":
            for desc_node in desc_nodes:
                if getattr(desc_node, "name", None):
                    desc_type = desc_node if desc_node.name == "a" else desc_node.find("a")
                    if desc_type:
                        type_name = desc_type.get_text(strip=True) or "—"
                        break
        if description:
            description = re.sub(
                r"^Тип:\s*.+?(?:\s+\.\s*|\.\s*|\n+)",
                "",
                description,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()
            description = _v8sh_compact_prose(description)
        bullet = f"- **{name}** ({type_name})"
        if description:
            bullet += f" — {description}"
        items.append(bullet)
        idx = look_ahead
    return items


def extract_v8sh_sections(soup: BeautifulSoup) -> dict[str, str]:
    """Extract normalized sections from V8SH help HTML for both Markdown and structured JSONL."""
    sections = {
        "description": "",
        "syntax": "",
        "fields": "",
        "params": "",
        "returns": "",
        "example": "",
        "see_also": "",
        "note": "",
        "version": "",
        "availability": "",
        "page_descriptor": "",
    }

    chapter_map = {
        "description": "Описание",
        "syntax": "Синтаксис",
        "fields": "Поля",
        "returns": "Возвращаемое значение",
        "note": "Примечание",
        "availability": "Доступность",
    }
    for key, prefix in chapter_map.items():
        chapter = _find_v8sh_chapter(soup, prefix)
        if chapter is not None:
            sections[key] = _v8sh_nodes_text(_iter_v8sh_chapter_nodes(chapter))
    if sections["returns"]:
        sections["returns"] = _v8sh_compact_prose(sections["returns"])

    params_chapter = _find_v8sh_chapter(soup, "Параметры")
    if params_chapter is not None:
        params_nodes = _iter_v8sh_chapter_nodes(params_chapter)
        rubric_params = _v8sh_rubric_params(params_nodes)
        sections["params"] = (
            "\n".join(rubric_params) if rubric_params else _v8sh_nodes_text(params_nodes)
        )

    example_chapter = _find_v8sh_chapter(soup, "Пример")
    if example_chapter is not None:
        example_nodes = _iter_v8sh_chapter_nodes(example_chapter)
        descriptions: list[str] = []
        code_blocks: list[str] = []
        for node in example_nodes:
            if getattr(node, "name", None) == "pre":
                code = node.get_text(separator="\n", strip=True)
                if code:
                    code_blocks.append(code)
            elif getattr(node, "name", None) == "table":
                code = "\n".join(
                    " ".join(cell.get_text(strip=True) for cell in row.find_all(["td", "th"]))
                    for row in node.find_all("tr")
                ).strip()
                if code:
                    code_blocks.append(code)
            else:
                text = _v8sh_nodes_text([node])
                if text:
                    descriptions.append(text)
        parts: list[str] = []
        if descriptions:
            parts.append(_normalize_md_text("\n".join(descriptions)))
        for code in code_blocks:
            parts.append(f"```bsl\n{code}\n```")
        sections["example"] = _normalize_md_text("\n\n".join(parts))

    see_also_chapter = _find_v8sh_chapter(soup, "См. также")
    if see_also_chapter is not None:
        names: list[str] = []
        for node in _iter_v8sh_chapter_nodes(see_also_chapter):
            if getattr(node, "find_all", None):
                for link in node.find_all("a"):
                    text = link.get_text(strip=True)
                    if text:
                        names.append(text)
        sections["see_also"] = (
            "\n".join(names)
            if names
            else _v8sh_nodes_text(_iter_v8sh_chapter_nodes(see_also_chapter))
        )

    version_heading = None
    for tag in soup.find_all(class_="V8SH_chapter"):
        raw = _v8sh_heading_text(tag) or ""
        if raw.startswith("Использование в версии"):
            version_heading = tag
            break
    if version_heading is not None:
        parts = []
        for sib in version_heading.next_siblings:
            if getattr(sib, "get", None) and "V8SH_chapter" in (sib.get("class") or []):
                break
            if getattr(sib, "get", None) and "V8SH_versionInfo" in (sib.get("class") or []):
                t = sib.get_text(separator=" ", strip=True)
                if t:
                    parts.append(t)
        sections["version"] = _normalize_md_text("\n".join(parts))
    if not sections["version"]:
        for wrapper in soup.find_all(class_="__SINCE_SHOW_STYLE__"):
            text = wrapper.get_text(" ", strip=True)
            if text:
                sections["version"] = _normalize_md_text(text)
                break

    sections["page_descriptor"] = _extract_v8sh_page_descriptor(soup)

    # Fallback for shlang_ru / inline format: <p class="Usual"><b>Section:<br></b>content</p>
    # Used by language operator topics (ВызватьИсключение, Попытка, etc.) that have no V8SH_chapter.
    if not any(v for k, v in sections.items() if k not in ("page_descriptor",)):
        _extract_usual_inline_sections(soup, sections)

    return sections


_USUAL_SECTION_MAP: dict[str, str] = {
    "синтаксис": "syntax",
    "параметры": "params",
    "возвращаемое значение": "returns",
    "описание варианта": "description",
    "описание": "description",
    "пример": "example",
    "см. также": "see_also",
    "примечание": "note",
    "доступность": "availability",
    "использование в версии": "version",
}


def _extract_usual_inline_sections(soup: BeautifulSoup, sections: dict[str, str]) -> None:
    """Fill *sections* from <p class="Usual"> inline-section format (shlang_ru operators)."""
    current_key: str | None = None
    buf: list[str] = []

    def _flush() -> None:
        if current_key and buf:
            text = _normalize_md_text(" ".join(buf).strip())
            if text:
                if sections.get(current_key):
                    sections[current_key] = sections[current_key] + "\n\n" + text
                else:
                    sections[current_key] = text
        buf.clear()

    title_tag = soup.find("h1", class_="V8SH_pagetitle")
    start_node = title_tag if title_tag else soup.find("body")
    if start_node is None:
        return

    for p in soup.find_all("p", class_="Usual"):
        # Detect bold header like <b>Синтаксис:<br></b> or <strong>Параметры: </strong>
        bold = p.find(["b", "strong"])
        header_text = ""
        if bold:
            raw = bold.get_text(" ", strip=True).rstrip(":").strip().lower()
            # Strip variant prefix "вариант синтаксиса: по выражению" → "синтаксис"
            for key in _USUAL_SECTION_MAP:
                if raw == key or raw.startswith(key):
                    header_text = key
                    break
        if header_text:
            _flush()
            current_key = _USUAL_SECTION_MAP[header_text]
            # Remainder of the <p> after the bold tag
            remainder = p.get_text(" ", strip=True)
            bold_text = bold.get_text(" ", strip=True)
            after = remainder[len(bold_text) :].strip() if remainder.startswith(bold_text) else ""
            if after:
                buf.append(after)
        elif current_key:
            # Collect pre blocks as code
            pre = p.find("pre")
            if pre:
                code = pre.get_text("\n", strip=True)
                if code:
                    buf.append(f"```bsl\n{code}\n```")
            else:
                text = p.get_text(" ", strip=True)
                if text:
                    buf.append(text)

    _flush()


def html_to_md_content(html_path) -> str:
    """
    Extract help article from HTML and return Markdown string.
    Sections: title, description, syntax, parameters, return value, examples, see also.
    Skips files over HELP_HTML_MAX_BYTES to avoid BeautifulSoup hang on huge HTML.
    """
    path = Path(html_path)
    if not path.exists():
        return ""
    text = _read_html_file(path)
    soup = BeautifulSoup(text, "html.parser")

    # Legacy schema: no V8SH_pagetitle → structured body (H1→#, H2–H6, tables)
    title_tag = soup.find("h1", class_="V8SH_pagetitle")
    if not title_tag:
        body = soup.find("body")
        if body:
            md_body = _legacy_body_to_md(body)
            if md_body.strip():
                return _normalize_md_text(md_body.strip())
        title = "Untitled"
    else:
        title = title_tag.get_text(strip=True)

    lines: list[str] = []
    lines.append(f"# {title}\n")

    sections = extract_v8sh_sections(soup)
    if sections["page_descriptor"]:
        lines.append(sections["page_descriptor"] + "\n\n")
    if sections["description"]:
        lines.append("## Описание\n\n")
        lines.append(sections["description"] + "\n\n")
    if sections["syntax"]:
        lines.append("## Синтаксис\n\n```\n")
        lines.append(sections["syntax"] + "\n")
        lines.append("```\n\n")
    if sections["fields"]:
        lines.append("## Поля\n\n")
        lines.append(sections["fields"] + "\n\n")
    if sections["params"]:
        lines.append("## Параметры\n\n")
        lines.append(sections["params"] + "\n\n")
    if sections["returns"]:
        lines.append("## Возвращаемое значение\n\n")
        lines.append(sections["returns"] + "\n\n")
    if sections["example"]:
        lines.append("## Пример\n\n")
        if sections["example"].startswith("```"):
            lines.append(sections["example"] + "\n\n")
        else:
            lines.append("```\n" + sections["example"] + "\n```\n\n")
    if sections["see_also"]:
        lines.append("## См. также\n\n")
        for target in sections["see_also"].splitlines():
            target = target.strip()
            if target:
                lines.append(f"- {target}\n")
        lines.append("\n")
    if sections["note"]:
        lines.append("## Примечание\n\n")
        lines.append(sections["note"] + "\n\n")
    if sections["version"]:
        lines.append("## Использование в версии\n\n")
        lines.append(sections["version"] + "\n\n")
    if sections["availability"]:
        lines.append("## Доступность\n\n")
        lines.append(sections["availability"] + "\n\n")

    out = "".join(lines).strip()
    if not out or out.strip() == (f"# {title}").strip():
        # Fallback: title + body text (catalog pages with only title)
        body = soup.find("body")
        if body:
            from ..shared import env_config

            lim = env_config.get_help_topic_body_max_chars()
            raw = body.get_text(separator="\n", strip=True)
            if lim > 0:
                raw = raw[:lim]
            out = f"# {title}\n\n" + raw
    return _normalize_md_text(out)


def _looks_like_html(path: Path) -> bool:
    """True if file has no extension and content starts like HTML (e.g. unpacked .hbk)."""
    try:
        head = _read_html_file(path)[:1024].lower()
        return "<html" in head or "<!doctype" in head
    except Exception:
        return False


# Extensions we never treat as HTML (binary or non-content)
_SKIP_EXTENSIONS = frozenset(
    {
        ".hbk",
        ".zip",
        ".7z",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".css",
        ".js",
        ".json",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".png",
        ".gif",
        ".jpg",
        ".jpeg",
        ".ico",
        ".bmp",
        ".webp",
        ".svg",
        ".db",
        ".dat",
        ".bin",
        ".idx",
    }
)


def iter_unpacked_hbk_html_files(stem_dir: Path) -> Iterator[Path]:
    """Yield HTML topic files under an unpacked .hbk directory.

    Platform UI books (e.g. ``1cv8_ru.hbk``) store most articles as extensionless files that
    still begin with ``<HTML>``; syntax/API books use ``*.html`` / ``*.htm``. Structured
    help and ingest must include both, not only ``*.html``.
    """
    stem_dir = Path(stem_dir)
    for p in stem_dir.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        ext = p.suffix.lower() if p.suffix else ""
        if ext in _SKIP_EXTENSIONS:
            continue
        if ext in (".html", ".htm"):
            yield p
        elif not ext and _looks_like_html(p):
            yield p


def build_docs(project_dir, output_dir):
    """
    Walk project_dir recursively (all subdirs, including PayloadData and any name).
    Process: .html, .htm, extension-less files that look like HTML, and any other
    file that _looks_like_html (e.g. .xml XHTML). Binary/non-content extensions are skipped.
    Convert each to .md in output_dir preserving structure.
    Returns list of created .md paths.
    """
    project_dir = Path(project_dir).resolve()
    output_dir = Path(output_dir).resolve()
    created: list[Path] = []
    for root, _, files in os.walk(project_dir):
        for name in files:
            if name.startswith("."):
                continue
            html_path = Path(root) / name
            ext = html_path.suffix.lower() if html_path.suffix else ""
            if ext in _SKIP_EXTENSIONS:
                continue
            is_html = ext in (".html", ".htm") or (
                ext in ("", ".xml", ".xhtml", ".st") and _looks_like_html(html_path)
            )
            if not is_html:
                continue
            try:
                rel = html_path.relative_to(project_dir)
            except ValueError:
                rel = html_path.name
            out_sub = output_dir / rel.parent
            out_sub.mkdir(parents=True, exist_ok=True)
            stem = rel.stem if rel.suffix else rel.name
            md_path = out_sub / (stem + ".md")
            content = html_to_md_content(html_path)
            if content:
                md_path.write_text(content, encoding="utf-8")
                created.append(md_path)
    return created
