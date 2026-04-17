#!/usr/bin/env python3
"""Install lightweight 1C context integration for Codex, Claude, or Cursor."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"


def _render_template(name: str, **values: str) -> str:
    template = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return template.format(**values)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _install_codex(repo_root: Path, skill_name: str) -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    target = codex_home / "skills" / skill_name
    target.mkdir(parents=True, exist_ok=True)
    content = _render_template(
        "agent_skill.md.tmpl",
        repo_root=str(repo_root),
        entrypoint=str(repo_root / "bin" / "onec-context"),
    )
    _write(target / "SKILL.md", content)
    return target


def _install_claude(repo_root: Path, skill_name: str) -> Path:
    target = Path.home().expanduser().resolve() / ".claude" / "skills" / skill_name
    target.mkdir(parents=True, exist_ok=True)
    content = _render_template(
        "agent_skill.md.tmpl",
        repo_root=str(repo_root),
        entrypoint=str(repo_root / "bin" / "onec-context"),
    )
    _write(target / "SKILL.md", content)
    return target


def _install_cursor(repo_root: Path, workspace: Path) -> Path:
    target = workspace.expanduser().resolve() / ".cursor" / "rules" / "onec-context.mdc"
    content = _render_template(
        "cursor_rule.mdc.tmpl",
        repo_root=str(repo_root),
        entrypoint=str(repo_root / "bin" / "onec-context"),
    )
    _write(target, content)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Install 1C context integration into an agent")
    parser.add_argument("--agent", required=True, choices=["codex", "claude", "cursor"])
    parser.add_argument("--skill-name", default="onec-context")
    parser.add_argument("--workspace", default=".", help="Cursor target workspace; ignored for Codex/Claude.")
    args = parser.parse_args()

    if args.agent == "codex":
        path = _install_codex(REPO_ROOT, args.skill_name)
    elif args.agent == "claude":
        path = _install_claude(REPO_ROOT, args.skill_name)
    else:
        path = _install_cursor(REPO_ROOT, Path(args.workspace))

    print(json.dumps({"agent": args.agent, "installed_to": str(path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
