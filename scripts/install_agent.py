#!/usr/bin/env python3
"""Install lightweight 1C context integration for Codex, Claude, or Cursor."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"
MAIN_BUNDLE_DIRS = ("bin", "docs", "scripts", "src", "tools", "templates", "skill")
MAIN_BUNDLE_FILES = ("README.md", "pyproject.toml")
SUPPLEMENTAL_SKILLS = (
    ("onec-platform-cli", "platform_cli_skill.md.tmpl", "platform_cli_reference.md.tmpl"),
    ("onec-query-strategy", "query_strategy_skill.md.tmpl", "query_strategy_reference.md.tmpl"),
    ("onec-explain-object", "explain_object_skill.md.tmpl", "explain_object_reference.md.tmpl"),
    ("onec-platform-fact-check", "platform_fact_check_skill.md.tmpl", "platform_fact_check_reference.md.tmpl"),
    ("onec-dev-standards", "dev_standards_skill.md.tmpl", "dev_standards_reference.md.tmpl"),
)
CURSOR_RULES = (
    ("onec-platform-cli.mdc", "cursor_platform_cli_rule.mdc.tmpl"),
    ("onec-query-strategy.mdc", "cursor_query_strategy_rule.mdc.tmpl"),
    ("onec-explain-object.mdc", "cursor_explain_object_rule.mdc.tmpl"),
    ("onec-platform-fact-check.mdc", "cursor_platform_fact_check_rule.mdc.tmpl"),
    ("onec-dev-standards.mdc", "cursor_dev_standards_rule.mdc.tmpl"),
)


def _render_template(name: str, **values: str) -> str:
    template = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return template.format(**values)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", ".venv", "build", "dist", ".git"),
    )


def _install_main_bundle(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for rel in MAIN_BUNDLE_DIRS:
        _copy_tree(REPO_ROOT / rel, target / rel)
    for rel in MAIN_BUNDLE_FILES:
        shutil.copy2(REPO_ROOT / rel, target / rel)


def _install_supplemental_skills(root: Path) -> dict[str, str]:
    installed: dict[str, str] = {}
    for skill_name, skill_template, reference_template in SUPPLEMENTAL_SKILLS:
        skill_root = root / skill_name
        if skill_root.exists():
            shutil.rmtree(skill_root)
        skill_root.mkdir(parents=True, exist_ok=True)
        _write(skill_root / "SKILL.md", _render_template(skill_template))
        _write(skill_root / "reference.md", _render_template(reference_template))
        installed[skill_name] = str(skill_root)
    return installed


def _install_codex(skill_name: str) -> dict[str, str]:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    target = codex_home / "skills" / skill_name
    _install_main_bundle(target)
    content = _render_template("agent_skill.md.tmpl")
    _write(target / "SKILL.md", content)
    installed = {"primary": str(target)}
    installed.update(_install_supplemental_skills(codex_home / "skills"))
    return installed


def _install_claude(skill_name: str) -> dict[str, str]:
    skills_root = Path.home().expanduser().resolve() / ".claude" / "skills"
    target = skills_root / skill_name
    _install_main_bundle(target)
    content = _render_template("agent_skill.md.tmpl")
    _write(target / "SKILL.md", content)
    installed = {"primary": str(target)}
    installed.update(_install_supplemental_skills(skills_root))
    return installed


def _install_cursor(skill_name: str, workspace: Path) -> dict[str, str]:
    workspace_root = workspace.expanduser().resolve()
    skills_root = workspace_root / ".cursor" / "skills"
    skill_root = skills_root / skill_name
    _install_main_bundle(skill_root)
    target = workspace_root / ".cursor" / "rules" / "onec-context.mdc"
    content = _render_template(
        "cursor_rule.mdc.tmpl",
        skill_rel_root=f".cursor/skills/{skill_name}",
    )
    _write(target, content)
    installed = {"primary": str(target)}
    installed.update(_install_supplemental_skills(skills_root))
    for rule_name, rule_template in CURSOR_RULES:
        _write(
            workspace_root / ".cursor" / "rules" / rule_name,
            _render_template(rule_template, skill_rel_root=f".cursor/skills/{skill_name}"),
        )
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(description="Install 1C context integration into an agent")
    parser.add_argument("--agent", required=True, choices=["codex", "claude", "cursor"])
    parser.add_argument("--skill-name", default="onec-context")
    parser.add_argument("--workspace", default=".", help="Cursor target workspace; ignored for Codex/Claude.")
    args = parser.parse_args()

    if args.agent == "codex":
        installed = _install_codex(args.skill_name)
    elif args.agent == "claude":
        installed = _install_claude(args.skill_name)
    else:
        installed = _install_cursor(args.skill_name, Path(args.workspace))

    print(
        json.dumps(
            {
                "agent": args.agent,
                "installed": installed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
