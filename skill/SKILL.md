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

1. Prefer `artifacts/metadata.kb.db.zst` for metadata questions.
2. Prefer `artifacts/code.pack.db.zst` for symbol and call graph questions.
3. Use `artifacts/config.dump.db.zst` only when exact source bytes or full file reads are required.
4. Use `artifacts/kb.db.zst` only for platform help/API lookup.

## Practical commands

```bash
python3 tools/verify_local_kb.py --artifacts-dir ./artifacts
python3 tools/local_kb_query.py --db ./artifacts/metadata.kb.db.zst --q "Document.РеализацияТоваровУслуг.Товары.Номенклатура" --exact --limit 10
python3 tools/query_code_pack.py --db ./artifacts/code.pack.db.zst symbols --q "УстановитьСтатусДокумента"
python3 tools/query_code_pack.py --db ./artifacts/code.pack.db.zst callers --symbol "УстановитьСтатусДокумента"
python3 tools/query_config_pack.py --db ./artifacts/config.dump.db.zst read --path "Documents/РеализацияТоваровУслуг/Ext/ObjectModule.bsl"
python3 tools/local_kb_query.py --db ./artifacts/kb.db.zst --q "HTTPСоединение.Получить" --limit 10
```

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
- `metadata XML export` is optional and may be absent from the bundle.
