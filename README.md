# Onec Context Toolkit

`onec-context-toolkit` — локальный source-first toolkit для 1С.

Он нужен для трёх вещей:

- поставить integration layer в `Codex`, `Claude`, `Cursor`
- собрать локальный context workspace в `.onec/` из `ConfigDump`, `HBK` и optional `metadata XML export`
- экспортировать готовый read-only runtime bundle

Agent/developer workflow, архитектурные правила и operational playbook вынесены в [AGENTS.md](AGENTS.md).
Дополнительный слой знаний по platform CLI, headless build и server administration вынесен в [docs/1c-platform-cli.md](docs/1c-platform-cli.md).

## Что нужно заранее

Минимально:

- Python `3.11+`
- `zstd`
- папка `ConfigDump` или другая поддерживаемая source tree
- доступ к `HBK` для стандартных профилей `base`, `metadata`, `dev`, `full`

`HBK` не нужен только в явном нестандартном сценарии с `--without-help`.

Проверить prerequisites можно так:

```bash
python scripts/doctor.py --workspace-init --hbk-base /opt/1cv8
```

## Быстрый старт

Toolkit ставится в managed user-level окружение.

По умолчанию:

- macOS / Linux:
  - virtualenv: `~/.local/share/onec-context-toolkit/venv`
  - launcher'ы: `~/.local/bin/onec-context`, `~/.local/bin/onec-bootstrap`, `~/.local/bin/onec-install-agent`
- Windows:
  - virtualenv: `%LOCALAPPDATA%\\onec-context-toolkit\\venv`
  - launcher'ы: `%LOCALAPPDATA%\\onec-context-toolkit\\bin\\onec-context.cmd`, `%LOCALAPPDATA%\\onec-context-toolkit\\bin\\onec-bootstrap.cmd`, `%LOCALAPPDATA%\\onec-context-toolkit\\bin\\onec-install-agent.cmd`

Это значит, что после bootstrap agent integration не зависит от текущего пути checkout'а репозитория.

Если launcher directory не находится в `PATH`, вызывайте bootstrap/install напрямую через `python scripts/...` или добавьте этот каталог в `PATH`.

## Установка

Основной путь:

```bash
python scripts/bootstrap.py
```

Быстрая установка вместе с Codex integration:

```bash
python scripts/bootstrap.py --agent codex
```

При установке integration toolkit ставит:

- основной skill `onec-context`
- дополнительный supplemental skill `onec-platform-cli` с картой по `1cv8`, `CREATEINFOBASE`, `ibcmd`, `ibsrv`, `ragent`, `rac`, `ras`

Если нужен unix convenience wrapper:

```bash
bin/onec-bootstrap --agent codex
```

Отдельная установка integration:

```bash
python scripts/install_agent.py --agent codex
python scripts/install_agent.py --agent claude
python scripts/install_agent.py --agent cursor --workspace /path/to/workspace
```

После managed install можно использовать stable launcher:

```bash
onec-install-agent --agent codex
```

## Инициализация workspace

Рекомендуемый первый шаг — собрать только базовый слой `help`:

```bash
onec-context init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/source \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

После этого дополнительные слои лучше достраивать по мере необходимости:

```bash
onec-context ensure --workspace-root /path/to/workspace --need metadata
onec-context ensure --workspace-root /path/to/workspace --need code
onec-context ensure --workspace-root /path/to/workspace --need full
```

Для расширения с несколькими возможными базовыми конфигурациями:

```bash
onec-context init \
  --workspace-root /path/to/extension \
  --source-path /path/to/extension \
  --source-kind extension \
  --profile base \
  --hbk-base /opt/1cv8 \
  --base-config "БухгалтерияПредприятия@3.0.184.16" \
  --base-config "УправлениеНашейФирмой@3.0.13.260"
```

Если нужен metadata fallback:

```bash
onec-context init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile metadata \
  --hbk-base /opt/1cv8 \
  --metadata-source /path/to/metadata_export
```

## Основные пользовательские команды

Проверить статус workspace:

```bash
onec-context status --workspace-root /path/to/workspace --strict
```

Достроить слой по мере необходимости:

```bash
onec-context ensure --workspace-root /path/to/workspace --need metadata
onec-context ensure --workspace-root /path/to/workspace --need code
onec-context ensure --workspace-root /path/to/workspace --need full
```

Посмотреть target'ы и pack paths:

```bash
onec-context resolve-packs --workspace-root /path/to/workspace
```

Если в source tree несколько `Configuration.xml`, toolkit соберёт несколько target'ов. В этом случае дальше нужно выбрать нужный `target` по имени и версии.

Проверить качество собранных packs:

```bash
onec-context verify --workspace-root /path/to/workspace
onec-context benchmark --workspace-root /path/to/workspace --loops 3
```

Экспортировать runtime bundle:

```bash
onec-context export --workspace-root /path/to/workspace --archive
```

## Что попадает в `.onec/`

В workspace toolkit собирает:

- `.onec/workspace.manifest.json`
- `.onec/packs/platform.<versions>.kb.db.zst`
- `.onec/packs/<source-identity>.metadata.kb.db.zst`
- `.onec/packs/<source-identity>.code.pack.db.zst`
- `.onec/packs/<source-identity>.config.dump.db.zst`
- `.onec/manifests/*.manifest.json`
- `.onec/cache/*.db`

Если `--source-path` указывает на папку с несколькими `Configuration.xml`, toolkit собирает отдельные target packs для каждого root.

## Что хранить в git

В repo стоит хранить:

- source code
- templates
- install scripts
- docs

Не стоит хранить:

- `.onec/`
- `build/`
- `dist/`
- большие `artifacts/*.zst`

Рекомендуемая модель распространения между разработчиками:

1. source repo как основной канал
2. optional exported bundle как transfer artifact
3. packs строятся локально в workspace или публикуются отдельными release assets

## Что важно помнить

- `HBK` — обязательный базовый слой для platform language/API knowledge
- `metadata XML export` — optional fallback или verification input, а не основной источник
- exported bundle — read-only; rebuild выполняется только из source repo
