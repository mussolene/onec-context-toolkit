#!/usr/bin/env python3
"""Check local prerequisites for the toolkit."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check host prerequisites for onec-context-toolkit")
    parser.add_argument("--workspace-init", action="store_true", help="Check tools needed for workspace initialization")
    parser.add_argument("--hbk-base", default=None, help="Optional HBK root; when present, unpack helpers are also checked")
    args = parser.parse_args()

    issues: list[str] = []
    checks = {
        "python": sys.version_info >= (3, 11),
        "zstd": _cmd_exists("zstd"),
    }
    if args.workspace_init:
        hbk_required = bool(args.hbk_base) or Path("/opt/1cv8").is_dir()
        if hbk_required:
            checks["7z_or_unzip"] = _cmd_exists("7z") or _cmd_exists("unzip")
            if not checks["7z_or_unzip"]:
                issues.append("Neither 7z nor unzip is available; HBK unpack fallback will be limited.")

    if not checks["python"]:
        issues.append("Python 3.11+ is required.")
    if not checks["zstd"]:
        issues.append("zstd CLI is required for pack build/query/export.")

    payload = {
        "ok": not issues,
        "checks": checks,
        "issues": issues,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
