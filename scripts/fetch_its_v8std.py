#!/usr/bin/env python3
"""Fetch 1C ITS v8std standards and save them as local markdown files.

ITS-only source: https://its.1c.ru/db/v8std
No external GitHub standards repositories are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


BASE = "https://its.1c.ru"
V8STD_MAIN = BASE + "/db/v8std"
V8STD_BROWSE = BASE + "/db/v8std/browse/13/-1"
CONTENT_RE = re.compile(r"/db/v8std/content/(\d+)/hdoc")
BROWSE_RE = re.compile(r"/db/v8std/browse/13/-1(?:/\d+)*")
NAV_NOISE = re.compile(
    r"^(Вход|Об 1С:ИТС|Тест-драйв|Заказать ИТС|Задать вопрос|Обновить ПО|"
    r"Оценить 1С|Купить кассу|Подбор КБК|Последние результаты|Подписаться на рассылку|"
    r"Мы используем файлы cookie|Принимаю|Назад|Результаты поиска|Содержание|Документ|"
    r"Тематические подборки|Календарь бухгалтера|Калькуляторы|Главная|"
    r"Инструкции по разработке на 1С|Методические материалы|© Фирма|Все права защищены)$",
    re.I,
)
BREADCRUMB_RE = re.compile(r"^\d+\.\s+\[.+\]\(.+\)\s*$")
MIN_REAL_CONTENT_CHARS = 150


def _sanitize_text(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", value)
    return value.strip()


def _safe_name(value: str, max_len: int = 80) -> str:
    value = _sanitize_text(value)
    chars: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in "-_ ":
            chars.append("_" if ch == " " else ch)
    out = "".join(chars).strip("_")
    if not out:
        out = hashlib.md5(value.encode("utf-8")).hexdigest()[:12]
    return out[:max_len]


def _build_opener(cookie: str | None) -> urllib.request.OpenerDirector:
    try:
        import certifi

        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ssl_context = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
    opener.addheaders.append(
        ("User-Agent", "Mozilla/5.0 (compatible; onec-context-its-v8std-fetcher/1.0)")
    )
    if cookie:
        opener.addheaders.append(("Cookie", cookie))
    return opener


def _detect_charset(resp: urllib.response.addinfourl, raw: bytes) -> str:
    content_type = resp.headers.get("Content-Type", "") or ""
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip("'\"").lower()
    head = raw[:8192].decode("ascii", errors="ignore")
    match = re.search(r'<meta[^>]+charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', head, re.I)
    if match:
        return match.group(1).strip().lower()
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        return "windows-1251"


def _fetch_text(url: str, opener: urllib.request.OpenerDirector, timeout: int = 40) -> str:
    with opener.open(urllib.request.Request(url), timeout=timeout) as resp:
        raw = resp.read()
    charset = _detect_charset(resp, raw)
    try:
        return _sanitize_text(raw.decode(charset, errors="replace"))
    except (LookupError, ValueError):
        return _sanitize_text(raw.decode("utf-8", errors="replace"))


def _extract_content_links(html: str, base_url: str) -> set[str]:
    links: set[str] = set()
    for match in CONTENT_RE.finditer(html):
        url = urljoin(base_url, match.group(0))
        links.add(url.split("?")[0].split("#")[0])
    return links


def _extract_browse_links(html: str, base_url: str) -> set[str]:
    links: set[str] = set()
    for match in BROWSE_RE.finditer(html):
        url = urljoin(base_url, match.group(0))
        links.add(url.split("?")[0].split("#")[0])
    return links


def _browse_path_from_url(url: str) -> list[str]:
    clean = url.split("?")[0].rstrip("/")
    if "/browse/13/-1/" not in clean:
        return []
    suffix = clean.split("/browse/13/-1/")[-1].strip("/")
    if not suffix:
        return []
    return [part for part in suffix.split("/") if part.isdigit()]


def _path_key(path_ids: list[str]) -> str:
    return "/".join(path_ids) if path_ids else ""


def _crawl_content_urls(
    opener: urllib.request.OpenerDirector,
    start_url: str,
    max_browse_pages: int,
    delay_sec: float,
) -> list[tuple[str, list[str]]]:
    seen: set[str] = set()
    queue: set[str] = {V8STD_MAIN, start_url}
    path_title_cache: dict[str, str] = {}
    out: list[tuple[str, list[str]]] = []
    while queue and (max_browse_pages <= 0 or len(seen) < max_browse_pages):
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url)
        time.sleep(delay_sec)
        try:
            html = _fetch_text(url, opener)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        path_ids = _browse_path_from_url(url)
        key = _path_key(path_ids)
        h1 = soup.find("h1")
        title = (h1.get_text(separator=" ", strip=True) if h1 else "").strip() or key or "v8std"
        if key:
            path_title_cache[key] = _sanitize_text(title)
        elif not path_ids:
            path_title_cache[""] = _sanitize_text(title) or "v8std"
        section_titles: list[str] = []
        for idx in range(len(path_ids)):
            part_key = _path_key(path_ids[: idx + 1])
            section_titles.append(path_title_cache.get(part_key, part_key))
        if not section_titles and not path_ids:
            section_titles = ["v8std"]
        for content_url in _extract_content_links(html, url):
            out.append((content_url, list(section_titles)))
        for browse_url in _extract_browse_links(html, url):
            if browse_url not in seen:
                queue.add(browse_url)
    return out


def _iframe_doc_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    iframe = soup.find("iframe", id="w_metadata_doc_frame")
    if not iframe:
        iframe = soup.find("iframe", src=re.compile(r"/db/content/v8std/"))
    if not iframe or not iframe.get("src"):
        return None
    src = str(iframe["src"]).strip()
    if not src.startswith("http"):
        src = urljoin(base_url, src)
    return src.split("#")[0] or None


def _extract_article_text(html: str, title: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body") or soup
    for tag in body.find_all(["nav", "header", "footer", "aside", "script", "style"]):
        tag.decompose()
    lines: list[str] = []
    for line in body.get_text(separator="\n", strip=True).splitlines():
        line = _sanitize_text(line)
        if not line or len(line) < 3:
            continue
        if NAV_NOISE.match(line) or BREADCRUMB_RE.match(line):
            continue
        lines.append(line)
    text = _sanitize_text("\n\n".join(lines))
    if not text:
        return None
    if title and text.strip() == title:
        return None
    if len(text.replace(title, "").strip()) < MIN_REAL_CONTENT_CHARS:
        return None
    return text


def fetch_its_items(
    opener: urllib.request.OpenerDirector,
    max_content: int,
    max_browse_pages: int,
    delay_sec: float,
) -> list[dict[str, Any]]:
    crawled = _crawl_content_urls(
        opener=opener,
        start_url=V8STD_BROWSE,
        max_browse_pages=max_browse_pages,
        delay_sec=delay_sec,
    )
    deduped: list[tuple[str, list[str]]] = []
    seen_ids: set[str] = set()
    for url, path_titles in crawled:
        content_id = url.split("/content/")[-1].split("/")[0] if "/content/" in url else ""
        if content_id and content_id in seen_ids:
            continue
        if content_id:
            seen_ids.add(content_id)
        deduped.append((url, path_titles))
    if max_content > 0:
        deduped = deduped[:max_content]

    items: list[dict[str, Any]] = []
    for url, path_titles in deduped:
        time.sleep(delay_sec)
        try:
            hdoc_html = _fetch_text(url, opener)
        except Exception:
            continue
        soup = BeautifulSoup(hdoc_html, "html.parser")
        h1 = soup.find("h1")
        title = _sanitize_text(h1.get_text(separator=" ", strip=True) if h1 else "")
        if not title and soup.title:
            raw = soup.title.get_text(separator=" ", strip=True)
            title = _sanitize_text(raw.split("::")[0].strip() if "::" in raw else raw)
        if not title and "/content/" in url:
            title = url.split("/content/")[-1].split("/")[0]
        if not title:
            title = "ITS v8std"

        article_text: str | None = None
        iframe_url = _iframe_doc_url(hdoc_html, url)
        if iframe_url:
            time.sleep(delay_sec)
            try:
                iframe_html = _fetch_text(iframe_url, opener)
                article_text = _extract_article_text(iframe_html, title)
            except Exception:
                article_text = None
        if not article_text:
            article_text = _extract_article_text(hdoc_html, title)
        if not article_text:
            continue

        first_para = article_text.split("\n\n")[0][:500].strip()
        content_id = url.split("/content/")[-1].split("/")[0] if "/content/" in url else ""
        items.append(
            {
                "title": title,
                "description": _sanitize_text(first_para),
                "code_snippet": _sanitize_text(f"# {title}\n\n{article_text}"),
                "detail_url": url,
                "source_ref": url,
                "source": "its.1c.ru",
                "source_site": "its.1c.ru",
                "content_id": content_id,
                "section_path": path_titles or ["v8std"],
            }
        )
    return items


def save_items(items: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in items:
        section_path = item.get("section_path") or ["v8std"]
        content_id = str(item.get("content_id") or "").strip()
        title = str(item.get("title") or "standard").strip()
        body = str(item.get("code_snippet") or "").strip()
        detail_url = str(item.get("detail_url") or "").strip()
        if not body:
            continue
        dst = output_dir
        for part in section_path:
            dst = dst / _safe_name(str(part), max_len=60)
        dst.mkdir(parents=True, exist_ok=True)
        slug = _safe_name(title, max_len=80)
        filename = f"{content_id}_{slug}.md" if content_id else f"{slug}.md"
        frontmatter = f"---\nsource: its.1c.ru\nurl: {detail_url}\nid: {content_id}\n---\n\n"
        (dst / filename).write_text(frontmatter + body + "\n", encoding="utf-8")
        saved += 1
    snapshot_path = output_dir / "_snapshot.json"
    snapshot_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": saved, "snapshot": str(snapshot_path)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch ITS v8std standards and save as markdown (ITS-only)"
    )
    parser.add_argument(
        "--output-dir",
        default="data/standards/its-v8std",
        help="Directory where ITS markdown files will be written",
    )
    parser.add_argument(
        "--max-content",
        type=int,
        default=int(os.environ.get("ITS_V8STD_MAX_CONTENT", "0") or "0"),
        help="Limit number of content pages (0 means no limit)",
    )
    parser.add_argument(
        "--max-browse-pages",
        type=int,
        default=int(os.environ.get("ITS_V8STD_MAX_BROWSE_PAGES", "0") or "0"),
        help="Limit number of browse pages (0 means no limit)",
    )
    parser.add_argument(
        "--delay-sec",
        type=float,
        default=float(os.environ.get("ITS_V8STD_DELAY", "0.2") or "0.2"),
        help="Delay between HTTP requests",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("ITS_AUTH_COOKIE", ""),
        help="Optional ITS auth cookie (or set ITS_AUTH_COOKIE env)",
    )
    args = parser.parse_args()

    opener = _build_opener(args.cookie.strip() or None)
    items = fetch_its_items(
        opener=opener,
        max_content=args.max_content,
        max_browse_pages=args.max_browse_pages,
        delay_sec=args.delay_sec,
    )
    result = save_items(items, Path(args.output_dir).expanduser().resolve())
    if result["saved"] <= 0:
        print(
            json.dumps(
                {
                    "source": "its.1c.ru/db/v8std",
                    "items_total": len(items),
                    "items_saved": result["saved"],
                    "output_dir": args.output_dir,
                    "snapshot_file": Path(result["snapshot"]).name,
                    "error": "No ITS v8std standards were fetched",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "source": "its.1c.ru/db/v8std",
                "items_total": len(items),
                "items_saved": result["saved"],
                "output_dir": args.output_dir,
                "snapshot_file": Path(result["snapshot"]).name,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
