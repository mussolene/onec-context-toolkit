# Canonical Proof Surface

Этот файл задаёт repeatable developer-facing сценарии, по которым удобно проверять `onec-context-toolkit`.
Цель не в том, чтобы покрыть все вопросы по 1С, а в том, чтобы показать ожидаемый route по слоям и дисциплину ответа агента.

## Как пользоваться

Для каждого сценария ниже:

1. Привести workspace в актуальное состояние через `status -> init/ensure`.
2. Явно выбрать `target`, если workspace multi-target.
3. Построить только минимально достаточный слой.
4. В ответе разделить `confirmed facts`, `code-derived inferences`, `unresolved assumptions`.

## Сценарий 1. Version-exact проверка platform API

- Задача: проверить, существует ли метод `HTTPСоединение.Получить` в конкретной версии платформы и как он называется в help.
- Минимальный слой: `platform`
- Почему этого достаточно: вопрос относится к platform help и language/API facts, а не к metadata или бизнес-логике конфигурации.
- Команды:

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/source \
  --profile base \
  --hbk-base /opt/1cv8 \
  --platform 8.3.25.1374

python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace --role platform --path-only
```

- Что должен доказать агент:
  - какой version-exact `platform` pack использован
  - что факт взят из platform help, а не из догадки по соседним API
  - есть ли unresolved assumption, если version-exact help не собран

## Сценарий 2. Реквизит документа и табличная часть

- Задача: ответить, где в `Document.РеализацияТоваровУслуг.Товары` находится реквизит `Номенклатура` и какой у него тип.
- Минимальный слой: `metadata`
- Почему этого достаточно: вопрос про структуру объекта, реквизиты и типы, а не про runtime behavior.
- Команды:

```bash
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need metadata

python scripts/onec_context.py query-kb \
  --db "$(python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace --role metadata --target <source-identity> --path-only)" \
  --q "Document.РеализацияТоваровУслуг.Товары.Номенклатура" \
  --exact --limit 10
```

- Что должен доказать агент:
  - что использовался именно `metadata` layer
  - какие facts подтверждены metadata pack
  - что выводов о бизнес-логике пока нет
  - что в single-target workspace `<source-identity>` можно получить через `resolve-packs` заранее и использовать дальше без переопределения

## Сценарий 3. Почему документ получает определённый статус

- Задача: найти, где вызывается `УстановитьСтатусДокумента` и какие обработчики реально влияют на результат.
- Минимальный слой: `code`
- Почему этого достаточно: для поиска callers/callees и влияния логики нужна code-level индексация модулей.
- Команды:

```bash
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need code

python scripts/onec_context.py query-code \
  --db "$(python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace --role code --target <source-identity> --path-only)" \
  symbols --q "УстановитьСтатусДокумента"
```

- Что должен доказать агент:
  - какие вызовы и обработчики подтверждены code pack
  - какие связи являются inference по коду
  - что без `code` слоя ответ был бы только предположением

## Сценарий 4. Финальное подтверждение по raw source/XML

- Задача: подтвердить exact XML или file-level представление формы/объекта, когда metadata и code уже дали вероятный ответ, но нужен lossless read.
- Минимальный слой: `full`
- Почему этого достаточно: здесь нужна не интерпретация, а финальное чтение `ConfigDump` как есть.
- Команды:

```bash
python scripts/onec_context.py ensure --workspace-root /path/to/workspace --need full

python scripts/onec_context.py query-config \
  --db "$(python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace --role full --target <source-identity> --path-only)" \
  find --q "РеализацияТоваровУслуг"
```

- Что должен доказать агент:
  - что для финального подтверждения выбран `full`, а не более дешёвый слой
  - какие facts подтверждены raw source/XML
  - что выводы, сделанные раньше по `metadata` или `code`, теперь подтверждены или опровергнуты

## Сценарий 5. Multi-target workspace

- Задача: в mono-repo с несколькими `Configuration.xml` выбрать правильную конфигурацию и только после этого ответить по объекту или коду.
- Минимальный слой: сначала выбор `target`, затем `metadata` или `code` по задаче
- Почему этого достаточно: в multi-target repo главный риск не в query syntax, а в том, что агент возьмёт не ту конфигурацию.
- Команды:

```bash
python scripts/onec_context.py status --workspace-root /path/to/workspace --strict
python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace
python scripts/onec_context.py resolve-packs --workspace-root /path/to/workspace --role metadata --all-targets
```

- Что должен доказать агент:
  - какой `target` выбран по имени и версии
  - что результаты не смешиваются между target'ами
  - что при неясном выборе target агент один раз запрашивает уточнение, а не продолжает наугад

## Сценарий 6. metadata XML export только как fallback или verification

- Задача: ответить по реквизиту, когда нормального `ConfigDump` нет, либо перепроверить спорный metadata fact.
- Минимальный профиль: `metadata`, то есть `platform + metadata`, с `metadata XML export` как fallback input
- Почему этого достаточно: здесь нужен metadata-level ответ, но в текущем toolkit профиль `metadata` всё равно строится поверх обязательного `platform` help layer. `metadata XML export` не заменяет source-first route, а страхует его.
- Команды:

```bash
python scripts/onec_context.py init \
  --workspace-root /path/to/workspace \
  --source-path /path/to/workspace \
  --profile metadata \
  --hbk-base /opt/1cv8 \
  --metadata-source /path/to/metadata_export
```

- Что должен доказать агент:
  - почему обычный `ConfigDump` route недоступен или недостаточен
  - что `metadata XML export` использован именно как fallback или verification layer
  - какие ограничения из-за этого остаются в ответе

## Минимальная форма ответа агента

```text
Target:
- <single target | config@version | not selected yet>

Used layers:
- platform
- metadata

Confirmed facts:
- ...

Code-derived inferences:
- ...

Unresolved assumptions:
- ...
```
