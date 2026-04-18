# Onec Context Toolkit

`onec-context-toolkit` — локальный toolkit для 1С-разработки.

Он решает три задачи:

- ставит self-contained skill pack в `Codex`, `Claude`, `Cursor`
- собирает локальный workspace context в `.onec/` из `ConfigDump` и `HBK`
- экспортирует готовый read-only runtime bundle

Если нужен только быстрый старт, достаточно пройти 3 шага ниже. Agent/developer workflow и внутренняя архитектура вынесены в [AGENTS.md](AGENTS.md). Отдельный слой знаний по platform CLI и headless/server операциям вынесен в [docs/1c-platform-cli.md](docs/1c-platform-cli.md).

## Первый запуск

Если ты новый пользователь, сделай ровно это:

1. Поставь skill в агента:

```bash
python scripts/install_agent.py --agent codex
```

Для `Cursor`:

```bash
python scripts/install_agent.py --agent cursor --workspace /path/to/workspace
```

2. Проверь prerequisites:

```bash
python scripts/doctor.py --workspace-init --hbk-base /opt/1cv8
```

3. Собери первый рабочий context:

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/source \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

После этого у тебя уже будет рабочий `help` layer. `metadata`, `code` и `full` достраиваются позже, только если они реально нужны.

## Что нужно заранее

Минимально:

- Python `3.11+`
- `zstandard` через локальное Python-окружение toolkit или `zstd` CLI как fallback
- папка `ConfigDump` или другая поддерживаемая source tree
- доступ к `HBK` для стандартных профилей `base`, `metadata`, `dev`, `full`
- `7z` или `unzip` только если они реально нужны для распаковки `HBK`

`HBK` не нужен только в явном нестандартном сценарии с `--without-help`.

На Windows вместо `/opt/1cv8` укажи свой каталог с файлами платформы.

Проверить prerequisites можно так:

```bash
python scripts/doctor.py --workspace-init --hbk-base /opt/1cv8
```

## Быстрый старт

Есть два режима:

- source-repo mode: работаешь из checkout этого репозитория
- installed skill mode: toolkit копируется прямо в skill directory агента и живёт там self-contained bundle

В обоих режимах локальное Python-окружение создаётся в корне самого toolkit:

- source repo: `.venv/` в checkout
- installed skill: `.venv/` внутри installed skill directory

Обычному пользователю достаточно помнить:

- `base` = только платформенная справка
- `metadata` = объекты, реквизиты, типы, табличные части, формы
- `code` = логика, обработчики, callers/callees
- `full` = raw source/XML и точные file-level чтения

## Установка

Основной путь для `Codex` и `Claude`:

```bash
python scripts/install_agent.py --agent codex
python scripts/install_agent.py --agent claude
```

При установке integration toolkit ставит:

- основной skill `onec-context`
- supplemental skill `onec-platform-cli` для `1cv8`, `CREATEINFOBASE`, `ibcmd`, `ibsrv`, `ragent`, `rac`, `ras`
- supplemental skill `onec-query-strategy` для cheapest-first route по `platform -> metadata -> code -> full`
- supplemental skill `onec-explain-object` для вопросов вида "как реквизит, флаг, форма или команда влияют на поведение"
- supplemental skill `onec-platform-fact-check` для проверки platform API и language facts по локальному help pack

Если нужен unix convenience wrapper:

```bash
./install/install_codex.sh
```

Отдельная установка integration:

```bash
python scripts/install_agent.py --agent codex
python scripts/install_agent.py --agent claude
python scripts/install_agent.py --agent cursor --workspace /path/to/workspace
```

Если нужно подготовить локальное Python-окружение в самом source repo:

```bash
python scripts/bootstrap.py --deps-only
```

Этот шаг ставит локальные Python-зависимости toolkit, включая `zstandard`.

## Быстрый старт для агента

Стартовый prompt, который сразу задаёт правильный маршрут работы:

```text
Работай с этой 1С-задачей через локальный onec-context toolkit.
Сначала проверь workspace и при необходимости инициализируй его.
Перед `init --profile base` найди `HBK` root: сначала в manifest workspace, но только если путь из него ещё существует, потом в `ONEC_HBK_BASE`, потом в `/opt/1cv8`; если его нет, один раз уточни путь у меня.
В качестве `HBK` path допустимы корень платформы, каталог конкретной версии или его `bin/`.
Используй onec-query-strategy, чтобы идти по cheapest-first route: сначала platform или metadata, потом code только если без него нельзя ответить, и full только для raw source/XML.
Если вопрос про объект, реквизит, форму, кнопку, флаг или влияние на поведение, используй onec-explain-object.
Если утверждаешь что-то про платформенный API, синтаксис языка, виды модулей или стандартные методы, сначала проверь это через onec-platform-fact-check.
Если target'ов несколько, выбери нужную конфигурацию по имени и версии или один раз уточни у меня.
Если знаешь версию платформы, используй её при build help pack, чтобы platform lookup был version-exact.
В ответе разделяй подтверждённые факты, выводы по коду и непроверенные предположения.
```

Если известны входные параметры, их лучше дописать сразу:

- путь к workspace
- путь к source tree
- версия платформы
- нужно ли сразу достраивать `metadata` или `code`

Это полезно, когда пользователь хочет сразу дать агенту задачу без ручного объяснения workflow.

## Инициализация workspace

Рекомендуемый первый шаг — собрать только базовый слой `help`:

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/source \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

После этого дополнительные слои лучше достраивать по мере необходимости:

```bash
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need metadata
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need code
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need full
```

Практически это означает:

- первый ответ по платформе можно получать сразу после `init --profile base`
- `metadata` нужно только для структуры конфигурации
- `code` нужно только для вопросов про логику и влияние одного куска кода на другой
- `full` нужен редко

Для расширения с несколькими возможными базовыми конфигурациями:

```bash
python scripts/onec_context.py init \
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
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile metadata \
  --hbk-base /opt/1cv8 \
  --metadata-source /path/to/metadata_export
```

## Основные пользовательские команды

Проверить статус workspace:

```bash
python scripts/onec_context.py status --workspace-root /path/to/workspace --strict
```

Достроить слой по мере необходимости:

```bash
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need metadata
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need code
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need full
```

Посмотреть target'ы и pack paths:

```bash
python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace
```

Если в source tree несколько `Configuration.xml`, toolkit соберёт несколько target'ов. В этом случае дальше нужно выбрать нужный `target` по имени и версии.

Если не хочется запоминать команды, `python scripts/onec_context.py --help` показывает краткую карту CLI и quick start прямо в help.

Проверить качество собранных packs:

```bash
python scripts/onec_context.py verify --workspace-root /path/to/workspace
python scripts/onec_context.py benchmark --workspace-root /path/to/workspace --loops 3
```

Экспортировать runtime bundle:

```bash
python scripts/onec_context.py export --workspace-root /path/to/workspace --archive
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
- installed agent skill — self-contained copy toolkit в skill directory агента; он не зависит от отдельного home-managed launcher
- supplemental skills не меняют pack model; они только задают правильный query route, behavior tracing и platform fact-check discipline
