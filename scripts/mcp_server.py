#!/usr/bin/env python3
"""Minimal MCP stdio server for compact agent access to onec-context."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onec_help.workspace_manifest import (  # noqa: E402
    all_target_packs,
    list_targets,
    load_bundle_manifest,
    load_workspace_manifest,
    platform_pack,
    resolve_pack_path,
    resolve_target_pack,
)
from scripts.status_workspace import collect_status  # noqa: E402


JSON = dict[str, Any]


def _schema(properties: JSON, required: list[str] | None = None) -> JSON:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: list[JSON] = [
    {
        "name": "onec_status",
        "description": "Check workspace manifest, pack health, and source drift.",
        "inputSchema": _schema(
            {
                "workspace_root": {"type": "string", "default": "."},
                "platform": {"type": "array", "items": {"type": "string"}, "default": []},
            }
        ),
    },
    {
        "name": "onec_ensure",
        "description": "Ensure requested workspace layers exist, rebuilding through existing toolkit lifecycle when needed.",
        "inputSchema": _schema(
            {
                "workspace_root": {"type": "string", "default": "."},
                "need": {
                    "oneOf": [
                        {"type": "string", "enum": ["platform", "standards", "metadata", "code", "full"]},
                        {
                            "type": "array",
                            "items": {"type": "string", "enum": ["platform", "standards", "metadata", "code", "full"]},
                        },
                    ]
                },
                "source_path": {"type": "string"},
                "source_kind": {"type": "string", "default": "auto"},
                "metadata_source": {"type": "string"},
                "hbk_base": {"type": "string"},
                "standards_dir": {"type": "string"},
                "platform": {"type": "array", "items": {"type": "string"}, "default": []},
                "base_config": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            ["need"],
        ),
    },
    {
        "name": "onec_resolve_packs",
        "description": "Resolve exact platform, standards, metadata, code, or full pack paths without hardcoding filenames.",
        "inputSchema": _schema(
            {
                "workspace_root": {"type": "string", "default": "."},
                "bundle_dir": {"type": "string"},
                "role": {"type": "string", "enum": ["platform", "standards", "metadata", "code", "full"]},
                "target": {"type": "string"},
                "all_targets": {"type": "boolean", "default": False},
                "path_only": {"type": "boolean", "default": False},
            }
        ),
    },
    {
        "name": "onec_query_kb",
        "description": "Query a platform, standards, or metadata knowledge pack. Provide db directly or workspace_root plus role/target.",
        "inputSchema": _schema(
            {
                "db": {"type": "string"},
                "workspace_root": {"type": "string", "default": "."},
                "role": {"type": "string", "enum": ["platform", "standards", "metadata"], "default": "platform"},
                "target": {"type": "string"},
                "q": {"type": "string"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                "domain": {"type": "string"},
                "version": {"type": "string"},
                "exact": {"type": "boolean", "default": False},
            },
            ["q"],
        ),
    },
    {
        "name": "onec_query_code",
        "description": "Query a code pack for stats, modules, symbols, callers, or callees.",
        "inputSchema": _schema(
            {
                "db": {"type": "string"},
                "workspace_root": {"type": "string", "default": "."},
                "target": {"type": "string"},
                "command": {"type": "string", "enum": ["stats", "modules", "symbols", "callers", "callees"]},
                "q": {"type": "string"},
                "symbol": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            ["command"],
        ),
    },
    {
        "name": "onec_query_config",
        "description": "Query a full config dump pack for stats, find, or text read operations.",
        "inputSchema": _schema(
            {
                "db": {"type": "string"},
                "workspace_root": {"type": "string", "default": "."},
                "target": {"type": "string"},
                "command": {"type": "string", "enum": ["stats", "find", "read"]},
                "q": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            ["command"],
        ),
    },
]


def _text(payload: object) -> JSON:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _tool_error(message: str) -> JSON:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def _root(value: str | None) -> Path:
    return Path(value or ".").expanduser().resolve()


def _load_manifest(args: JSON) -> tuple[str, Path, JSON]:
    if args.get("bundle_dir"):
        bundle_root = _root(str(args["bundle_dir"]))
        manifest_path = bundle_root / "bundle.manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"bundle manifest is missing: {manifest_path}")
        return "bundle", bundle_root, load_bundle_manifest(bundle_root)
    workspace_root = _root(str(args.get("workspace_root") or "."))
    manifest_path = workspace_root / ".onec" / "workspace.manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"workspace manifest is missing: {manifest_path}; run onec_ensure or onec-context init")
    return "workspace", workspace_root, load_workspace_manifest(workspace_root)


def _resolve(args: JSON) -> JSON | str:
    manifest_kind, manifest_root, manifest = _load_manifest(args)
    role = args.get("role")
    target = args.get("target")
    path_only = bool(args.get("path_only"))
    all_targets = bool(args.get("all_targets"))

    targets_payload = []
    for item in list_targets(manifest):
        packs = item.get("packs") or {}
        if isinstance(packs, dict):
            item = {
                **item,
                "packs": {
                    name: str(resolve_pack_path(path_value, base_root=manifest_root))
                    for name, path_value in packs.items()
                    if isinstance(path_value, str)
                },
            }
        targets_payload.append(item)

    if not role:
        return {
            "kind": manifest_kind,
            "platform": (
                str(resolve_pack_path(platform_pack(manifest), base_root=manifest_root))
                if platform_pack(manifest)
                else None
            ),
            "standards": _resolve_role_path(manifest, manifest_root, "standards"),
            "targets": targets_payload,
        }

    if role in {"platform", "standards"}:
        resolved_path = _resolve_role_path(manifest, manifest_root, str(role))
        if not resolved_path:
            raise FileNotFoundError(f"{role} pack is missing")
        return resolved_path if path_only else {"role": role, "path": resolved_path}

    if all_targets:
        resolved_all = {
            target_name: str(resolve_pack_path(path_value, base_root=manifest_root))
            for target_name, path_value in all_target_packs(manifest, role=str(role)).items()
        }
        if not resolved_all:
            raise FileNotFoundError(f"{role} pack is missing")
        if path_only and len(resolved_all) == 1:
            return next(iter(resolved_all.values()))
        return {"role": role, "targets": resolved_all}

    resolved = resolve_target_pack(manifest, role=str(role), target=str(target) if target else None)
    if not resolved:
        raise ValueError(f"{role} pack path is ambiguous or missing; provide target or all_targets=true")
    resolved_path = str(resolve_pack_path(resolved, base_root=manifest_root))
    return resolved_path if path_only else {"role": role, "target": target, "path": resolved_path}


def _resolve_role_path(manifest: JSON, manifest_root: Path, role: str) -> str | None:
    if role == "platform":
        value = platform_pack(manifest)
    else:
        packs = manifest.get("packs") or {}
        value = packs.get(role) if isinstance(packs, dict) else None
    return str(resolve_pack_path(value, base_root=manifest_root)) if isinstance(value, str) else None


def _resolve_db(args: JSON, role: str) -> str:
    if args.get("db"):
        return str(_root(str(args["db"])))
    resolve_args: JSON = {
        "workspace_root": args.get("workspace_root") or ".",
        "role": role,
        "path_only": True,
    }
    if args.get("target"):
        resolve_args["target"] = args["target"]
    resolved = _resolve(resolve_args)
    if not isinstance(resolved, str):
        raise ValueError(f"could not resolve {role} pack")
    return resolved


def _run_python(args: list[str]) -> str:
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(detail or f"command failed with exit code {proc.returncode}")
    return proc.stdout.strip()


def _call_ensure(args: JSON) -> JSON:
    needs = args.get("need")
    if isinstance(needs, str):
        needs = [needs]
    if not isinstance(needs, list) or not needs:
        raise ValueError("need must be a string or non-empty array")
    cmd = [str(REPO_ROOT / "scripts" / "ensure_workspace.py"), "--workspace-root", str(_root(args.get("workspace_root")))]
    for need in needs:
        cmd.extend(["--need", str(need)])
    option_map = {
        "source_path": "--source-path",
        "source_kind": "--source-kind",
        "metadata_source": "--metadata-source",
        "hbk_base": "--hbk-base",
        "standards_dir": "--standards-dir",
    }
    for key, flag in option_map.items():
        if args.get(key):
            cmd.extend([flag, str(args[key])])
    for version in args.get("platform") or []:
        cmd.extend(["--platform", str(version)])
    for base_config in args.get("base_config") or []:
        cmd.extend(["--base-config", str(base_config)])
    output = _run_python(cmd)
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(output)
    return {"output": output}


def _capture_tool(module_name: str, argv: list[str]) -> str:
    module = __import__(module_name, fromlist=["main"])
    old_argv = sys.argv
    buffer = io.StringIO()
    try:
        sys.argv = [module_name, *argv]
        with contextlib.redirect_stdout(buffer):
            rc = module.main()
    finally:
        sys.argv = old_argv
    if rc:
        raise RuntimeError(f"{module_name} failed with exit code {rc}")
    return buffer.getvalue().strip()


def _call_tool(name: str, args: JSON) -> JSON:
    if name == "onec_status":
        return _text(collect_status(_root(args.get("workspace_root")), requested_platforms=list(args.get("platform") or [])))
    if name == "onec_ensure":
        return _text(_call_ensure(args))
    if name == "onec_resolve_packs":
        return _text(_resolve(args))
    if name == "onec_query_kb":
        db = _resolve_db(args, str(args.get("role") or "platform"))
        argv = ["--db", db, "--q", str(args["q"]), "--limit", str(args.get("limit") or 10)]
        if args.get("domain"):
            argv.extend(["--domain", str(args["domain"])])
        if args.get("version"):
            argv.extend(["--version", str(args["version"])])
        if args.get("exact"):
            argv.append("--exact")
        return _text(_capture_tool("tools.local_kb_query", argv))
    if name == "onec_query_code":
        db = _resolve_db(args, "code")
        command = str(args["command"])
        argv = ["--db", db, command]
        if command in {"modules", "symbols"}:
            if not args.get("q"):
                raise ValueError(f"{command} requires q")
            argv.extend(["--q", str(args["q"]), "--limit", str(args.get("limit") or 20)])
        elif command in {"callers", "callees"}:
            if not args.get("symbol"):
                raise ValueError(f"{command} requires symbol")
            argv.extend(["--symbol", str(args["symbol"]), "--limit", str(args.get("limit") or 20)])
        return _text(_capture_tool("tools.query_code_pack", argv))
    if name == "onec_query_config":
        db = _resolve_db(args, "full")
        command = str(args["command"])
        argv = ["--db", db, command]
        if command == "find":
            if not args.get("q"):
                raise ValueError("find requires q")
            argv.extend(["--q", str(args["q"]), "--limit", str(args.get("limit") or 20)])
        elif command == "read":
            if not args.get("path"):
                raise ValueError("read requires path")
            argv.extend(["--path", str(args["path"])])
        return _text(_capture_tool("tools.query_config_pack", argv))
    raise KeyError(f"unknown tool: {name}")


def _response(request_id: object, result: object | None = None, error: JSON | None = None) -> JSON:
    payload: JSON = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _handle(message: JSON, *, debug: bool = False) -> JSON | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    try:
        if method == "initialize":
            return _response(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "onec-context-mcp", "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return _response(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = message.get("params") or {}
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            return _response(request_id, _call_tool(str(tool_name), arguments))
        raise NotImplementedError(f"unsupported method: {method}")
    except Exception as exc:  # noqa: BLE001 - MCP should return errors instead of crashing.
        detail = "".join(traceback.format_exception(exc)) if debug else str(exc)
        if method == "tools/call":
            return _response(request_id, _tool_error(detail))
        return _response(request_id, error={"code": -32000, "message": detail})


def serve(debug: bool = False) -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = _handle(message, debug=debug)
        except Exception as exc:  # noqa: BLE001
            response = _response(None, error={"code": -32700, "message": str(exc)})
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the onec-context MCP stdio server")
    parser.add_argument("--debug", action="store_true", help="Return Python tracebacks in MCP errors")
    args = parser.parse_args()
    return serve(debug=args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
