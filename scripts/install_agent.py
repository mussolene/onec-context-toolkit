#!/usr/bin/env python3
"""Install lightweight 1C context integration for Codex, Claude, or Cursor."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"


def _default_tool_home() -> Path:
    home = Path.home().expanduser().resolve()
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or str(home / "AppData" / "Local")
        ).expanduser().resolve()
        return base / "onec-context-toolkit"
    return home / ".local" / "share" / "onec-context-toolkit"


def _default_entrypoint() -> Path:
    tool_home = _default_tool_home()
    if os.name == "nt":
        return tool_home / "bin" / "onec-context.cmd"
    return Path.home().expanduser().resolve() / ".local" / "bin" / "onec-context"


DEFAULT_ENTRYPOINT = str(_default_entrypoint())
DEFAULT_TOOL_HOME = str(_default_tool_home())


def _render_template(name: str, **values: str) -> str:
    template = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return template.format(**values)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _install_codex(tool_home: str, entrypoint: str, skill_name: str) -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    target = codex_home / "skills" / skill_name
    target.mkdir(parents=True, exist_ok=True)
    content = _render_template(
        "agent_skill.md.tmpl",
        repo_root=str(tool_home),
        entrypoint=str(entrypoint),
    )
    _write(target / "SKILL.md", content)
    return target


def _install_claude(tool_home: str, entrypoint: str, skill_name: str) -> Path:
    target = Path.home().expanduser().resolve() / ".claude" / "skills" / skill_name
    target.mkdir(parents=True, exist_ok=True)
    content = _render_template(
        "agent_skill.md.tmpl",
        repo_root=str(tool_home),
        entrypoint=str(entrypoint),
    )
    _write(target / "SKILL.md", content)
    return target


def _install_cursor(tool_home: str, entrypoint: str, workspace: Path) -> Path:
    target = workspace.expanduser().resolve() / ".cursor" / "rules" / "onec-context.mdc"
    content = _render_template(
        "cursor_rule.mdc.tmpl",
        repo_root=str(tool_home),
        entrypoint=str(entrypoint),
    )
    _write(target, content)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Install 1C context integration into an agent")
    parser.add_argument("--agent", required=True, choices=["codex", "claude", "cursor"])
    parser.add_argument("--skill-name", default="onec-context")
    parser.add_argument("--workspace", default=".", help="Cursor target workspace; ignored for Codex/Claude.")
    parser.add_argument("--entrypoint", default=DEFAULT_ENTRYPOINT, help="Stable onec-context launcher path or command")
    parser.add_argument("--tool-home", default=DEFAULT_TOOL_HOME, help="Displayed toolkit home for installed integration")
    args = parser.parse_args()

    if args.agent == "codex":
        path = _install_codex(args.tool_home, args.entrypoint, args.skill_name)
    elif args.agent == "claude":
        path = _install_claude(args.tool_home, args.entrypoint, args.skill_name)
    else:
        path = _install_cursor(args.tool_home, args.entrypoint, Path(args.workspace))

    print(
        json.dumps(
            {
                "agent": args.agent,
                "installed_to": str(path),
                "entrypoint": args.entrypoint,
                "tool_home": args.tool_home,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
