# Onec Context Toolkit

![Onec Context Toolkit hero](docs/readme/hero.svg)

`onec-context-toolkit` превращает 1С-репозиторий в локальный source-first context для агентов. Он ставит self-contained integration в `Codex`, `Claude`, `Cursor`, собирает workspace packs в `.onec/` из `ConfigDump` и `HBK`, а затем умеет экспортировать read-only runtime bundle для offline lookup.

![Workflow](docs/readme/workflow.svg)

## Что это даёт

| Задача | Что делает toolkit |
| --- | --- |
| Установка в агента | Копирует self-contained skill bundle и supplemental guidance layers |
| Локальный context | Строит `platform`, `metadata`, `code`, `full` packs только когда они реально нужны |
| Контроль drift | Проверяет stale state по platform version, config version и source snapshot |
| Runtime bundle | Экспортирует готовый read-only bundle без rebuild logic |

Если нужен operational workflow и архитектурная модель, они вынесены в [AGENTS.md](AGENTS.md). Отдельный supplemental слой по platform CLI и headless/server операциям лежит в [docs/1c-platform-cli.md](docs/1c-platform-cli.md).

## Быстрый старт за 3 шага

### 1. Поставить integration

Для `Codex`:

```bash
python scripts/install_agent.py --agent codex
```

Для `Claude`:

```bash
python scripts/install_agent.py --agent claude
```

Для `Cursor`:

```bash
python scripts/install_agent.py --agent cursor --workspace /path/to/workspace
```

### 2. Проверить prerequisites

```bash
python scripts/doctor.py --workspace-init --hbk-base /opt/1cv8
```

`HBK` path может указывать на:

- корень платформы
- каталог конкретной версии
- `bin/` внутри каталога версии

На Windows это особенно полезно: можно передавать не только корневой каталог платформы, но и version-specific `bin/`, где реально лежат `.hbk`.

### 3. Собрать базовый workspace

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/source \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

После этого у workspace уже есть `help` layer. Остальные слои достраиваются по запросу:

```bash
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need metadata
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need code
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need full
```

## Что нужно заранее

- Python `3.11+`
- `zstandard` через локальное Python-окружение toolkit или `zstd` CLI как fallback
- `ConfigDump` или другая поддерживаемая source tree
- доступ к `HBK` для стандартных профилей `base`, `metadata`, `dev`, `full`
- `7z` или `unzip`, если они нужны для распаковки `.hbk`

`HBK` не нужен только в явном нестандартном сценарии с `--without-help`.

## Модель слоёв

| Профиль / need | Что строится | Когда нужен |
| --- | --- | --- |
| `base` | `platform` help pack | platform API, language facts, syntax |
| `metadata` | `platform` + `metadata` | объекты, реквизиты, табличные части, формы |
| `dev` / `code` | `platform` + `metadata` + `code` | обработчики, callers/callees, влияние логики |
| `full` | всё выше + lossless `ConfigDump` pack | raw XML, точные file-level reads, final confirmation |

Ключевой принцип: не строить дорогой слой заранее, если вопрос можно закрыть более дешёвым route.

## Канонический proof surface

Повторяемые developer-facing сценарии собраны в [examples/proof-surface.md](examples/proof-surface.md). Это не маркетинговые лозунги, а canonical tasks с ожидаемым route по слоям, примером запроса и тем, что именно агент должен доказать.

Дополнительная живая доказательная база с обезличенными archetypes из большой production-like 1С-кодовой базы собрана в [examples/live-codebase-proof.md](examples/live-codebase-proof.md). Она нужна, чтобы проверять toolkit не только на учебных сценариях, но и на реальных формах, командах, табличных частях и command modules.

В минимальный proof surface входят:

- version-exact проверка платформенного метода через `platform`
- разбор реквизита, табличной части или формы через `metadata`
- поиск влияния на поведение через `code`
- финальное подтверждение по raw source/XML через `full`
- multi-target сценарий, где сначала выбирается нужная конфигурация, а уже потом идёт query

Если нужно быстро проверить позиционирование toolkit на реальном вопросе разработчика 1С, начинайте с этих сценариев, а не с произвольного prompt.

## Сравнение с соседними инструментами

| Инструмент | Что закрывает хорошо | Где граница относительно `onec-context-toolkit` |
| --- | --- | --- |
| `1C:EDT` | IDE, проектная работа, навигация, сборка и ежедневная разработка | `onec-context-toolkit` не заменяет IDE. Он даёт source-first lifecycle для agent work: `status -> init/ensure -> resolve-packs -> query/verify/export`. |
| `BSL Language Server` | Диагностика, LSP-навигация, проверки кода BSL | Это code intelligence слой, а не orchestration над `platform` / `metadata` / `code` / `full` packs и не workspace/export lifecycle. |
| AI-facing platform-context tool | Доступ к platform help и language facts для ассистента | Такой слой полезен для help/API lookup, но сам по себе не решает drift, target selection, локальный metadata/code/full routing и export готового runtime bundle. |

Идея toolkit не в том, чтобы конкурировать с IDE или LSP по каждой функции. Он закрывает другой слой: воспроизводимый локальный context для агента поверх реального 1С source tree и platform help.

## Как выглядит рабочий цикл

```text
status -> init/ensure -> resolve-packs -> query/verify/export
```

Практические команды:

```bash
python scripts/onec_context.py status --workspace-root /path/to/workspace --strict
python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace
python scripts/onec_context.py verify --workspace-root /path/to/workspace
python scripts/onec_context.py benchmark --workspace-root /path/to/workspace --loops 3
python scripts/onec_context.py export --workspace-root /path/to/workspace --archive
```

Если `--source-path` указывает на папку с несколькими `Configuration.xml`, toolkit собирает несколько target packs и записывает их в `.onec/workspace.manifest.json -> targets`. В этом режиме нельзя хардкодить первый попавшийся pack path: сначала нужно выбрать target по имени и версии.

## Контракт ответа агента

Если агент отвечает с опорой на toolkit, ответ должен быть структурирован так:

1. `Target`
   Указать выбранный target. Если target один, можно явно написать, что workspace single-target. Если target'ов несколько, нужно назвать конфигурацию и версию или честно отметить, что без выбора target ответ будет недостоверным.
2. `Использованные слои`
   Назвать, какие слои использовались: `platform`, `metadata`, `code`, `full`.
3. `Подтверждённые факты`
   Только то, что подтверждено pack/query results или version-exact platform help.
4. `Выводы по коду`
   Отдельно от фактов описать inference: как код влияет на поведение, какие модули участвуют, что из этого следует.
5. `Непроверенные предположения`
   Явно перечислить, чего toolkit пока не доказал: отсутствующий слой, невыбранный target, неполный source tree, спорное место в платформе.

Короткая версия правила: не смешивать facts, inference и assumptions в один абзац; всегда называть слой и target, откуда взят ответ.

## Режимы использования

### Source repo mode

Работа идёт прямо из checkout этого репозитория. Локальное окружение живёт в `.venv/` в корне repo.

```bash
python scripts/bootstrap.py --deps-only
```

### Installed skill mode

Toolkit копируется прямо в skill directory агента и живёт как self-contained bundle. Локальное окружение создаётся уже внутри установленного skill directory.

При установке integration toolkit ставит:

- основной skill `onec-context`
- supplemental skill `onec-platform-cli`
- supplemental skill `onec-query-strategy`
- supplemental skill `onec-explain-object`
- supplemental skill `onec-platform-fact-check`

## Prompt для агента

<details>
<summary>Показать стартовый prompt</summary>

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
В ответе всегда называй target и использованные слои, а затем разделяй подтверждённые факты, выводы по коду и непроверенные предположения.
```

</details>

Если известны входные параметры, полезно дописать сразу:

- путь к workspace
- путь к source tree
- версия платформы
- нужно ли заранее строить `metadata` или `code`

Для multi-target workspace полезно сразу дописывать и ожидаемый `target`, чтобы агент не начал query по неверной конфигурации.

## Инициализация и дополнительные сценарии

### Базовый `help` слой

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/source \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.2.19.130
```

### Расширение с несколькими base configs

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

### Metadata fallback через `metadata XML export`

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile metadata \
  --hbk-base /opt/1cv8 \
  --metadata-source /path/to/metadata_export
```

`metadata XML export` здесь остаётся fallback или verification layer. Нормальный happy path для toolkit всё равно начинается с `ConfigDump` + `HBK`, а `metadata XML export` используется, когда source tree неполный или нужно перепроверить спорные реквизиты и типы.

## FAQ и сбои, которые надо закрывать сразу

### Какой `HBK` path правильный?

Toolkit принимает три формы:

- корень с несколькими версиями, например `/opt/1cv8`
- каталог конкретной версии, например `C:\Program Files\1cv8\8.3.25.1374`
- `bin/` внутри конкретной версии, например `C:\Program Files\1cv8\8.3.25.1374\bin`

Если известна версия платформы, лучше передавать и `--platform <VERSION>`, чтобы help pack был version-exact.

### Что делать, если в workspace несколько target'ов?

1. Выполнить `python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace`.
2. Посмотреть `targets` и выбрать нужный target по имени и версии.
3. Во всех `query-*` командах и в ответах агента использовать этот target последовательно.

Нельзя молча смешивать результаты из нескольких target'ов.

### Когда нужен `metadata XML export`?

Не как default route. Его стоит использовать только в двух режимах:

- fallback, если нет нормального `ConfigDump`
- verification layer, если нужно перепроверить спорный metadata fact

Если есть полноценный source tree, сначала должен работать обычный source-first workflow.

### Как восстановиться после stale workspace или drift?

Минимальный путь такой:

```bash
python scripts/onec_context.py status --workspace-root /path/to/workspace --strict
python scripts/onec_context.py init --workspace-root /path/to/workspace --source-path /path/to/source --profile base --hbk-base /opt/1cv8 --platform <VERSION>
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need metadata
```

Если stale оказался только один слой, достаточно `ensure --need metadata|code|full`. Если поменялись версия платформы, версия конфигурации или сам source snapshot, считайте старые ответы недоказанными, пока `status` и rebuild не пройдены заново.

## Что лежит в `.onec/`

Toolkit собирает:

- `.onec/workspace.manifest.json`
- `.onec/packs/platform.<versions>.kb.db.zst`
- `.onec/packs/<source-identity>.metadata.kb.db.zst`
- `.onec/packs/<source-identity>.code.pack.db.zst`
- `.onec/packs/<source-identity>.config.dump.db.zst`
- `.onec/manifests/*.manifest.json`
- `.onec/cache/*.db`

## Что хранить в git

Стоит хранить:

- source code
- templates
- install scripts
- docs

Не стоит хранить:

- `.onec/`
- `build/`
- `dist/`
- большие `artifacts/*.zst`

Рекомендуемая модель распространения:

1. source repo как основной канал
2. optional exported bundle как transfer artifact
3. packs строятся локально в workspace или публикуются как release assets

## Полезные ссылки

- [AGENTS.md](AGENTS.md) — operational workflow для агентов и разработчиков
- [docs/1c-platform-cli.md](docs/1c-platform-cli.md) — platform CLI и headless/server reference
- `python scripts/onec_context.py --help` — карта CLI и quick start прямо в help
