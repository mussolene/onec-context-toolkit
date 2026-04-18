# AGENTS

Этот файл описывает agent/developer workflow для `onec-context-toolkit`.

## Назначение

Toolkit работает как source-first слой локального 1С context:

- ставит integration layer в `Codex`, `Claude`, `Cursor`
- инициализирует конкретный workspace в `.onec/`
- собирает packs из локальных источников
- проверяет drift по версии платформы и версии конфигурации
- экспортирует runtime bundle из уже собранного workspace

## Архитектурная модель

Один toolkit, несколько слоёв ответственности:

- `runtime/integration`
  - install scripts для `codex`, `claude`, `cursor`
  - общий CLI `onec-context`
- `source adapters`
  - `ConfigDump` конфигурации
  - `ConfigDump` расширения
  - `metadata XML export` как optional fallback / verification
  - `HBK` платформенной справки как обязательный source для language/API слоя
- `pack builders`
  - `platform help pack`
  - `metadata pack`
  - `code pack`
  - optional `full pack`
- `workspace binding`
  - `.onec/workspace.manifest.json`
  - хранит source-kind, base configs, versions, built packs, optional sources

## Источники и pack'и

Primary route:

- `ConfigDump` source tree -> `metadata pack`
- `HBK` source tree -> `platform help pack`
- `ConfigDump` source tree -> optional `code pack`
- `ConfigDump` source tree -> optional `full pack`

Optional route:

- `metadata XML export` -> fallback metadata source или проверочный слой

`metadata XML export` не является обязательным шагом. Его стоит оставлять как:

- fallback, если нет нормального source tree
- verification layer для спорных мест
- дополнительный источник для уточнения реквизитов и типов

## Слои по умолчанию

Базовый обязательный слой:

- `help` (`--profile base`)

Опциональные слои:

- `metadata` (`ensure --need metadata` или `--profile metadata`) для реквизитов, типов, табличных частей и форм
- `code.pack` (`ensure --need code` или `--profile dev`) для анализа логики
- `config.dump` (`ensure --need full` или `--profile full`) для lossless file-level reads

## Обязательный operational loop

Если работа идёт по workspace, правильный цикл такой:

1. Проверить workspace:
   - `onec-context status --workspace-root <repo> --strict`
2. Если `.onec/workspace.manifest.json` отсутствует или stale:
   - `onec-context init --workspace-root <repo> --source-path <repo-or-config-root> --profile base`
3. Если для ответа не хватает слоя:
   - `onec-context ensure --workspace-root <repo> --need metadata|code|full`
4. Разрешить точные pack paths:
   - `onec-context resolve-packs --workspace-root <repo>`
5. Делать query/verify/export только после этого

`status` сравнивает текущий source snapshot и pack manifests и показывает, что нужно пересобрать.

## Версии и drift

Когда меняется:

- версия платформы
- версия расширяемой конфигурации
- сам source tree

нужно повторно пройти `status -> init/ensure -> status`.

Для расширений важно явно хранить возможные `base_configs`.

## Multi-root и target model

Если `--source-path` указывает на папку с несколькими `Configuration.xml`, toolkit не должен падать.
Он собирает отдельные target packs для каждого root и записывает их в `.onec/workspace.manifest.json -> targets`.

Agent должен выбирать target осознанно и не хардкодить pack filenames.

## Команды для агентов

Проверить prerequisites:

```bash
onec-context doctor --workspace-init --hbk-base /opt/1cv8
```

Статус:

```bash
onec-context status --workspace-root /path/to/workspace --strict
```

Достроить слой только когда он реально нужен:

```bash
onec-context ensure --workspace-root /path/to/workspace --need metadata
onec-context ensure --workspace-root /path/to/workspace --need code
```

Разрешить pack paths:

```bash
onec-context resolve-packs --workspace-root /path/to/workspace
onec-context resolve-packs --workspace-root /path/to/workspace --role platform --path-only
onec-context resolve-packs --workspace-root /path/to/workspace --role metadata --all-targets
```

Metadata query:

```bash
onec-context query-kb \
  --db "$(onec-context resolve-packs --workspace-root /path/to/workspace --role metadata --target <source-identity> --path-only)" \
  --q "Document.РеализацияТоваровУслуг.Товары.Номенклатура" \
  --exact --limit 10
```

Code query:

```bash
onec-context query-code \
  --db "$(onec-context resolve-packs --workspace-root /path/to/workspace --role code --target <source-identity> --path-only)" \
  symbols --q "УстановитьСтатусДокумента"
```

Full pack query:

```bash
onec-context query-config \
  --db "$(onec-context resolve-packs --workspace-root /path/to/workspace --role full --target <source-identity> --path-only)" \
  find --q "РеализацияТоваровУслуг"
```

Verify and benchmark:

```bash
onec-context verify --workspace-root /path/to/workspace
onec-context benchmark --workspace-root /path/to/workspace --loops 3
```

## Что внутри репозитория

- `bin/onec-context` — CLI entrypoint для repo-local use
- `scripts/init_workspace.py` — source-first init
- `scripts/status_workspace.py` — drift/status check
- `scripts/install_agent.py` — integration install
- `scripts/export_skill_bundle.py` — bundle export из `.onec/`
- `scripts/build_local_kb.py` — help/metadata builder
- `scripts/build_code_pack.py` — code pack builder
- `scripts/build_config_pack.py` — full lossless pack builder
- `src/onec_help/metadata_index/` — source-driven metadata parsing from `ConfigDump`
- `tools/` — runtime query/verify/benchmark tools
- `templates/` — templates для agent installs и bundle docs

## Практические выводы

- Один универсальный skill проще, чем много skill-per-config
- Packs должны быть project-bound, а не repo-global
- `HBK` должен быть обязательным базовым слоем
- `metadata` и `code.pack` лучше собирать lazy
- `ConfigDump` должен быть основным источником для metadata и code
- `metadata XML export` лучше оставлять optional fallback/verification
- Для version drift нужен штатный `status`, а не ручная догадка
- Самая тяжёлая часть первого старта — `code.pack`, поэтому она не должна быть дефолтом

## Полный rebuild одного workspace

```bash
onec-context status --workspace-root .
onec-context init --workspace-root . --source-path . --profile full --hbk-base /opt/1cv8 --platform 8.2.19.130
onec-context verify --workspace-root .
onec-context export --workspace-root . --archive
```
