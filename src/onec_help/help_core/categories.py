"""Parse __categories__ and build TOC tree (from syntax1C.py)."""

import os
import re
from pathlib import Path

from .html2md import read_file_with_encoding_fallback


def parse_content_file(content_path) -> list:
    """
    Parse __categories__ file and return list of item names (files/dirs).
    Format: {num,"name", ...} or multiple such blocks in one line.
    """
    structure = []
    path = Path(content_path)
    if not path.exists():
        return structure
    content = read_file_with_encoding_fallback(path)
    # Match {num,"name" or },"name" (blocks separated by })
    for match in re.finditer(r'(?:\{\d+|}),"([^"]+)"', content):
        structure.append(match.group(1))
    return structure


def extract_html_title(html_path) -> str:
    """Extract title (h1 or title) from HTML file."""
    path = Path(html_path)
    if not path.exists():
        return "Untitled"
    content = read_file_with_encoding_fallback(path)[:2000]
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
    if title_match:
        return re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
    if title_match:
        return title_match.group(1).strip()
    return "Untitled"


def build_tree(
    base_dir,
    content_structure,
    current_path="",
):
    """
    Build TOC tree from __categories__ structure and files.
    Returns list of nodes: {title, path, children}.
    """
    base = Path(base_dir)
    tree: list[dict] = []
    for item in content_structure:
        full_path = base / current_path.replace("/", os.sep) / item
        if full_path.is_dir():
            sub_categories = full_path / "__categories__"
            if sub_categories.exists():
                sub_structure = parse_content_file(sub_categories)
            else:
                sub_structure = [
                    f.name for f in full_path.iterdir() if f.suffix == ".html" or f.is_dir()
                ]
            tree.append(
                {
                    "title": item,
                    "path": "",
                    "children": build_tree(
                        base_dir,
                        sub_structure,
                        os.path.join(current_path, item),
                    ),
                }
            )
        elif full_path.is_file() and (
            item.endswith(".html") or item.endswith(".htm") or "." not in item
        ):
            title = extract_html_title(full_path)
            rel_path = os.path.join(current_path, item).replace("\\", "/")
            tree.append(
                {
                    "title": title,
                    "path": rel_path,
                    "children": [],
                }
            )
    return tree


def find_categories_root(start_dir):
    """Find a directory containing __categories__ (walking up or into common layout)."""
    start = Path(start_dir).resolve()
    for d in [start, *start.parents]:
        if (d / "__categories__").exists():
            return d
    # Common 1C help layout: .../source/FileStorage/objects or .../objects
    for sub in ["source/FileStorage/objects", "objects", "source"]:
        p = start / sub
        if p.exists() and (p / "__categories__").exists():
            return p
    return None
