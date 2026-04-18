---
name: onec-context-bundle
description: Self-contained offline runtime bundle for 1C context lookup. Uses packaged metadata, code, optional full ConfigDump, and optional platform help packs without a server.
---

# Onec Context Bundle

## When to use

Use this bundle when:

- the workspace already has packaged local packs;
- you need exact lookup for requisites, tabular sections, form attributes, or type info;
- you need fast module/symbol/caller lookup in BSL;
- you need optional file-level reads from a lossless `ConfigDump` pack;
- you need optional platform help lookup.

## Runtime order

1. Resolve exact artifact paths with `python3 tools/resolve_packs.py --bundle-dir .`; do not hardcode filenames.
2. If multiple targets are present, choose the correct one by name/version before querying.
3. Prefer `targets.<source-identity>.packs.metadata` for metadata questions when it is present.
4. Prefer `targets.<source-identity>.packs.code` for symbol and call graph questions when it is present.
5. Use `targets.<source-identity>.packs.full` only when exact source bytes or full file reads are required.
6. Use `packs.platform` only for platform help/API lookup.

## Practical commands

```bash
python3 tools/verify_local_kb.py --artifacts-dir ./artifacts
python3 tools/resolve_packs.py --bundle-dir .
```

## Supplemental reference

- For platform CLI, standalone server, cluster administration, `1cv8`, `CREATEINFOBASE`, `ibcmd`, `ibsrv`, `ragent`, `rac`, and `ras`, use `docs/1c-platform-cli.md` in this bundle as the compact reference layer.

## Interpretation

- `metadata_objects`: metadata object level hit
- `metadata_fields`: requisite, tabular section, tabular section requisite, form attribute, or form command
- `modules`: BSL module path-level hit
- `symbols`: declaration-level hit
- `callers` / `callees`: usage and effect chain

## Constraints

- This bundle is read-only.
- It does not rebuild packs itself.
- If a required artifact is missing, state that explicitly.
- If several targets exist and the correct one is unclear, ask which configuration or extension should be used.
- `targets.*.packs.metadata`, `targets.*.packs.code`, and `targets.*.packs.full` may be absent in minimal bundles.
- `metadata XML export` is optional and may be absent from the bundle.
