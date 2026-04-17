# Onec Context Toolkit

`onec-context-toolkit` — source-first toolkit для локального 1С agent context.

Репозиторий не должен хранить готовые большие артефакты как source-of-truth. Его задача:
- поставить integration layer в `Codex`, `Claude`, `Cursor`;
- инициализировать конкретный workspace в `.onec/`;
- собрать packs из локальных источников;
- проверять drift по версии платформы и версии конфигурации;
- экспортировать готовый runtime bundle из уже собранного workspace.

## Что считается правильной моделью

Один toolkit, несколько слоёв ответственности:

- `runtime/integration`
  - install scripts для `codex`, `claude`, `cursor`
  - общий CLI `bin/onec-context`
- `source adapters`
  - `ConfigDump` конфигурации
  - `ConfigDump` расширения
  - `metadata XML export` как optional fallback / verification
  - `HBK` платформенной справки как обязательный source для language/API слоя
- `pack builders`
  - `metadata pack`
  - `code pack`
  - optional `full pack`
  - `platform help pack`
- `workspace binding`
  - `.onec/workspace.manifest.json`
  - хранит source-kind, base configs, versions, built packs, optional sources

Это даёт понятный pipeline для конфигураций, расширений, обработок и нескольких рабочих контекстов на одной платформе.

## Что собирать из чего

Primary route:
- `ConfigDump` source tree -> `metadata pack`
- `HBK` source tree -> `platform help pack`
- `ConfigDump` source tree -> optional `code pack`
- `ConfigDump` source tree -> optional `full pack`

Optional route:
- `metadata XML export` -> fallback metadata source или проверочный слой

`metadata XML export` не является обязательным шагом. Его стоит оставлять как:
- fallback, если нет нормального source tree;
- verification layer для спорных мест;
- дополнительный источник для уточнения реквизитов/типов.

Базовый обязательный слой для агента:
- `help + metadata`

Опциональные слои:
- `code.pack` для анализа логики
- `config.dump` для lossless file-level reads

## Понятный режим при подъёме версий

Когда меняется:
- версия платформы;
- версия расширяемой конфигурации;
- сам source tree;

правильный маршрут такой:

1. `onec-context status --workspace-root <repo> --strict`
2. если workspace stale, rebuild через `onec-context init ...`
3. `status` повторно
4. только потом query/export

`status` смотрит в `.onec/workspace.manifest.json`, сравнивает текущий source snapshot и pack manifests и явно показывает, что нужно пересобрать.

## Быстрый старт

Установка Python deps:

```bash
python3 -m pip install -e .
```

или полностью через bootstrap:

```bash
bin/onec-bootstrap
```

Быстрый bootstrap для первого запуска:

```bash
bin/onec-bootstrap --agent codex
```

или сразу с инициализацией workspace:

```bash
bin/onec-bootstrap \
  --agent codex \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

Установить integration отдельно:

```bash
./install/install_codex.sh
./install/install_claude.sh
./install/install_cursor.sh --workspace /path/to/workspace
```

Инициализировать workspace из `ConfigDump`:

```bash
bin/onec-context init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

Собрать слой анализа логики:

```bash
bin/onec-context init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile dev \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

Полный слой с lossless pack:

```bash
bin/onec-context init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile full \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

Для расширения с несколькими возможными базовыми конфигурациями:

```bash
bin/onec-context init \
  --workspace-root /path/to/extension \
  --source-path /path/to/extension \
  --source-kind extension \
  --base-config "БухгалтерияПредприятия@3.0.184.16" \
  --base-config "УправлениеНашейФирмой@3.0.13.260"
```

Если нужно только metadata fallback:

```bash
bin/onec-context init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --metadata-source /path/to/metadata_export
```

## Основные команды

Статус:

```bash
bin/onec-context status --workspace-root /path/to/workspace --strict
```

Query по metadata:

```bash
python3 tools/local_kb_query.py \
  --db /path/to/workspace/.onec/packs/metadata.kb.db.zst \
  --q "Document.РеализацияТоваровУслуг.Товары.Номенклатура" \
  --exact --limit 10
```

Query по code pack:

```bash
python3 tools/query_code_pack.py \
  --db /path/to/workspace/.onec/packs/code.pack.db.zst \
  symbols --q "УстановитьСтатусДокумента"
```

Verify:

```bash
python3 tools/verify_local_kb.py --workspace-root /path/to/workspace
python3 tools/benchmark_local_kb.py --workspace-root /path/to/workspace --loops 3
```

Экспорт runtime bundle из уже инициализированного workspace:

```bash
bin/onec-context export --workspace-root /path/to/workspace --archive
```

## Что попадает в `.onec/`

В конкретном workspace toolkit собирает:

- `.onec/packs/kb.db.zst` как обязательный language/API layer
- `.onec/workspace.manifest.json`
- `.onec/packs/metadata.kb.db.zst`
- `.onec/packs/code.pack.db.zst` при `--profile dev|full` или `--with-code`
- `.onec/packs/config.dump.db.zst` при `--profile full` или `--with-full-pack`
- `.onec/manifests/*.manifest.json`
- `.onec/cache/*.db`

## Что хранить в git, а что нет

В публичном repo стоит хранить:
- source code
- templates
- install scripts
- docs

Не стоит хранить:
- `.onec/`
- `build/`
- `dist/`
- большие `artifacts/*.zst`

Рекомендуемая поставка между разработчиками:

1. source repo как основной канал
2. optional exported bundle как transfer artifact
3. packs строятся локально в workspace или публикуются отдельными release assets

Это минимизирует проблему хранения тяжёлых артефактов в git history.

## Что внутри репозитория

- `bin/onec-context` — единая CLI entrypoint
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

- Один универсальный skill проще, чем много skill-per-config.
- Packs должны быть project-bound, а не repo-global.
- `HBK + metadata` должны быть обязательным базовым слоем.
- `ConfigDump` должен быть основным источником для metadata/code.
- `metadata XML export` лучше оставить optional fallback/verification, а не primary source.
- Для расширений важно явно хранить возможные `base_configs`.
- Для version drift нужен штатный `status`, а не ручная догадка.
- Самая тяжёлая часть первого старта — `code.pack`, поэтому она не должна быть дефолтом.

Если нужен полный rebuild одного workspace, правильный цикл такой:

```bash
bin/onec-context status --workspace-root .
bin/onec-context init --workspace-root . --source-path . --profile full --hbk-base /opt/1cv8 --platform 8.2.19.130
python3 tools/verify_local_kb.py --workspace-root .
bin/onec-context export --workspace-root . --archive
```
