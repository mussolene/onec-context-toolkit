"""Minimal BSL parsing and extraction helpers for compact code packs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


try:
    import tree_sitter_bsl as _ts_bsl
    from tree_sitter import Language
    from tree_sitter import Parser as _TsParser

    _BSL_LANGUAGE = Language(_ts_bsl.language())
    _TS_AVAILABLE = True
except Exception:  # pragma: no cover - optional runtime dependency
    _BSL_LANGUAGE = None
    _TS_AVAILABLE = False


_RE_PROC = re.compile(
    r"^(?P<indent>\s*)(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_VAR_DECL = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<vars>[^;]+);",
    re.IGNORECASE | re.MULTILINE,
)
_RE_CALL = re.compile(
    r"(?:^|[^.\w])(?P<name>[А-ЯЁа-яёA-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)
_RE_DOC_LINE = re.compile(r"^\s*//\s?(?P<text>.*)$")
_RE_CYRILLIC = re.compile(r"[А-ЯЁа-яё]")
_BSL_KEYWORDS = frozenset(
    {
        "если",
        "пока",
        "для",
        "каждого",
        "из",
        "по",
        "цикл",
        "процедура",
        "функция",
        "перем",
        "возврат",
        "новый",
        "попытка",
        "исключение",
        "конецпопытки",
        "if",
        "while",
        "for",
        "each",
        "in",
        "do",
        "loop",
        "procedure",
        "function",
        "var",
        "return",
        "new",
        "try",
        "except",
        "endtry",
    }
)


@dataclass
class ParsedModule:
    path: str
    content: str
    tree: Any


@dataclass
class Symbol:
    name: str
    kind: str
    line: int
    end_line: int
    is_export: bool
    container: str | None
    signature: str
    doc_comment: str
    file_path: str


@dataclass
class Call:
    caller_file: str
    caller_line: int
    caller_name: str | None
    callee_name: str
    callee_args_count: int = 0


class BslParser:
    """Minimal BSL parser with tree-sitter primary path and regex fallback."""

    def __init__(self) -> None:
        self._ts_parser: Any = None
        if _TS_AVAILABLE:
            self._ts_parser = _TsParser(_BSL_LANGUAGE)

    def parse_file(self, path: str | Path) -> ParsedModule:
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8-sig", errors="replace")
        tree = None
        if self._ts_parser is not None:
            tree = self._ts_parser.parse(content.encode("utf-8"))
        return ParsedModule(path=str(file_path), content=content, tree=tree)


def extract_symbols(parsed: ParsedModule) -> list[Symbol]:
    if parsed.tree is not None:
        try:
            return _extract_symbols_ts(parsed)
        except Exception:
            pass
    return _extract_symbols_regex(parsed)


def extract_calls(parsed: ParsedModule) -> list[Call]:
    if parsed.tree is not None:
        try:
            return _extract_calls_ts(parsed)
        except Exception:
            pass
    return _extract_calls_regex(parsed)


def _proc_signature(kind: str, name: str, params: str | list[str], is_export: bool) -> str:
    params_str = ", ".join(params) if isinstance(params, list) else params
    if _RE_CYRILLIC.search(name):
        kw = "Функция" if kind == "function" else "Процедура"
        export_kw = " Экспорт" if is_export else ""
    else:
        kw = "Function" if kind == "function" else "Procedure"
        export_kw = " Export" if is_export else ""
    return f"{kw} {name}({params_str}){export_kw}"


def _extract_doc_comment(lines: list[str], line_idx: int) -> str:
    chunks: list[str] = []
    idx = line_idx - 1
    while idx >= 0:
        match = _RE_DOC_LINE.match(lines[idx])
        if not match:
            break
        chunks.append(match.group("text").strip())
        idx -= 1
    chunks.reverse()
    return " ".join(part for part in chunks if part)


def _node_text(node: Any) -> str:
    text = getattr(node, "text", b"")
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def _proc_name_from_node(node: Any) -> str:
    for child in getattr(node, "children", []):
        if getattr(child, "type", "") == "identifier":
            return _node_text(child)
    return ""


def _extract_symbols_ts(parsed: ParsedModule) -> list[Symbol]:
    symbols: list[Symbol] = []
    lines = parsed.content.splitlines()

    def visit(node: Any, container: str | None) -> None:
        node_type = getattr(node, "type", "")

        if node_type in ("procedure_definition", "function_definition"):
            sym = _proc_symbol_from_ts(node, parsed.path, lines, container)
            if sym is not None:
                symbols.append(sym)
                container = sym.name

        if node_type in ("var_definition", "var_statement"):
            symbols.extend(_var_symbols_from_ts(node, parsed.path, container))

        for child in getattr(node, "children", []):
            visit(child, container)

    visit(parsed.tree.root_node, None)
    return sorted(symbols, key=lambda item: (item.line, item.name.lower()))


def _proc_symbol_from_ts(
    node: Any, file_path: str, lines: list[str], container: str | None
) -> Symbol | None:
    name = ""
    params: list[str] = []
    is_export = False
    for child in getattr(node, "children", []):
        child_type = getattr(child, "type", "")
        if child_type == "identifier":
            name = _node_text(child)
        elif child_type == "parameters":
            params = [
                _node_text(param)
                for param in getattr(child, "children", [])
                if getattr(param, "type", "") == "parameter"
            ]
        elif child_type == "EXPORT_KEYWORD":
            is_export = True

    if not name:
        return None

    kind = "function" if getattr(node, "type", "") == "function_definition" else "procedure"
    line = node.start_point[0] + 1
    return Symbol(
        name=name,
        kind=kind,
        line=line,
        end_line=node.end_point[0] + 1,
        is_export=is_export,
        container=container,
        signature=_proc_signature(kind, name, params, is_export),
        doc_comment=_extract_doc_comment(lines, line - 1),
        file_path=file_path,
    )


def _var_symbols_from_ts(node: Any, file_path: str, container: str | None) -> list[Symbol]:
    is_export = any(getattr(child, "type", "") == "EXPORT_KEYWORD" for child in node.children)
    names = [_node_text(child) for child in node.children if getattr(child, "type", "") == "identifier"]
    out: list[Symbol] = []
    for name in names:
        out.append(
            Symbol(
                name=name,
                kind="variable",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_export=is_export,
                container=container,
                signature=f"Var {name}",
                doc_comment="",
                file_path=file_path,
            )
        )
    return out


def _extract_symbols_regex(parsed: ParsedModule) -> list[Symbol]:
    content = parsed.content
    lines = content.splitlines()
    end_positions = sorted(content[: match.start()].count("\n") for match in _RE_END_PROC.finditer(content))
    symbols: list[Symbol] = []

    for match in _RE_PROC.finditer(content):
        line_idx = content[: match.start()].count("\n")
        name = match.group("name")
        keyword = match.group("kw").lower()
        kind = "function" if keyword in ("функция", "function") else "procedure"
        params = match.group("params").strip()
        is_export = bool(match.group("export"))
        end_line_idx = next((item for item in end_positions if item > line_idx), line_idx)
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=line_idx + 1,
                end_line=end_line_idx + 1,
                is_export=is_export,
                container=None,
                signature=_proc_signature(kind, name, params, is_export),
                doc_comment=_extract_doc_comment(lines, line_idx),
                file_path=parsed.path,
            )
        )

    for match in _RE_VAR_DECL.finditer(content):
        line_idx = content[: match.start()].count("\n")
        vars_part = match.group("vars")
        is_export = "экспорт" in vars_part.lower() or "export" in vars_part.lower()
        cleaned = re.sub(r"\b(?:Экспорт|Export)\b", "", vars_part, flags=re.IGNORECASE)
        for name in re.findall(r"[А-ЯЁа-яёA-Za-z_]\w*", cleaned):
            symbols.append(
                Symbol(
                    name=name,
                    kind="variable",
                    line=line_idx + 1,
                    end_line=line_idx + 1,
                    is_export=is_export,
                    container=None,
                    signature=f"Var {name}",
                    doc_comment="",
                    file_path=parsed.path,
                )
            )

    return sorted(symbols, key=lambda item: (item.line, item.name.lower()))


def _extract_calls_ts(parsed: ParsedModule) -> list[Call]:
    calls: list[Call] = []

    def visit(node: Any, container: str | None) -> None:
        node_type = getattr(node, "type", "")
        if node_type in ("procedure_definition", "function_definition"):
            name = _proc_name_from_node(node)
            if name:
                container = name
        if node_type == "method_call":
            call = _call_from_ts(node, parsed.path, container)
            if call is not None:
                calls.append(call)
        for child in getattr(node, "children", []):
            visit(child, container)

    visit(parsed.tree.root_node, None)
    return sorted(calls, key=lambda item: (item.caller_line, item.callee_name.lower()))


def _call_from_ts(node: Any, file_path: str, container: str | None) -> Call | None:
    callee_name = ""
    args_count = 0
    for child in getattr(node, "children", []):
        child_type = getattr(child, "type", "")
        if child_type == "identifier":
            callee_name = _node_text(child)
        elif child_type == "arguments":
            args_count = sum(
                1 for item in getattr(child, "children", []) if getattr(item, "type", "") not in ("(", ")", ",")
            )
    if not callee_name or callee_name.lower() in _BSL_KEYWORDS:
        return None
    return Call(
        caller_file=file_path,
        caller_line=node.start_point[0] + 1,
        caller_name=container,
        callee_name=callee_name,
        callee_args_count=args_count,
    )


def _extract_calls_regex(parsed: ParsedModule) -> list[Call]:
    calls: list[Call] = []
    current_proc: str | None = None
    lines = parsed.content.splitlines()
    proc_header = re.compile(
        r"^\s*(?:Процедура|Procedure|Функция|Function)\s+(?P<name>\w+)",
        re.IGNORECASE,
    )
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        proc_match = proc_header.match(stripped)
        if proc_match:
            current_proc = proc_match.group("name")
            continue
        if _RE_END_PROC.match(stripped):
            current_proc = None
            continue
        for match in _RE_CALL.finditer(line):
            callee_name = match.group("name")
            if callee_name.lower() in _BSL_KEYWORDS:
                continue
            rest = line[match.end() :]
            args_count = 0 if rest.lstrip().startswith(")") else 1
            depth = 1
            for ch in rest:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                elif ch == "," and depth == 1:
                    args_count += 1
            calls.append(
                Call(
                    caller_file=parsed.path,
                    caller_line=line_idx + 1,
                    caller_name=current_proc,
                    callee_name=callee_name,
                    callee_args_count=args_count,
                )
            )
    return sorted(calls, key=lambda item: (item.caller_line, item.callee_name.lower()))
