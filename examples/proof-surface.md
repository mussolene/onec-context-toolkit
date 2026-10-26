# Проверка toolkit

Это воспроизводимые сценарии приёмки, а не отчёт о производительности на любой
платформе. Команды запускаются из корня toolkit. Замените пути и версию своими.
Исходные HBK и конфигурации не входят в репозиторий.

## 1. Установка и готовая справка

```sh
python3 scripts/install_agent.py --agent codex --platform-pack /path/to/platform-pack.db.zst
```

Ожидание: основной skill содержит исполняемые инструменты, справочные материалы
и `artifacts/platform.kb.db.zst`. Обновление сохраняет подготовленное окружение
и базу. Отдельные специализированные skills ставятся только с `--supplemental`.

## 2. Подготовка и повторное использование

```sh
python3 scripts/onec_context.py ensure --workspace-root /path/to/project --need platform --hbk-base /path/to/platform --platform 8.5.1.1343
python3 scripts/onec_context.py status --workspace-root /path/to/project --strict
python3 scripts/onec_context.py resolve-packs --workspace-root /path/to/project
```

Повторите `ensure` без изменения источника. Ожидание: `changed: false`, архив
платформы не перезаписан, временные файлы извлечения не накопились. При изменении
HBK или сборщика нужна новая сборка. Исходные HBK, архив и действующий кэш
сохраняются намеренно.

## 3. Точный ответ и границы источника

```sh
python3 scripts/onec_context.py query-kb --workspace-root /path/to/project --q 'Структура.Вставить' --exact --version 8.5.1.1343 --json
python3 scripts/onec_context.py query-kb --workspace-root /path/to/project --q 'ПрочитатьJSON' --exact --version 8.5.1.1343 --detail full --json
python3 scripts/onec_context.py query-kb --workspace-root /path/to/project --q 'НесуществующийМетодПроверкиToolkit' --exact --json
```

Ожидание: у найденного результата есть соответствующее имя, источник и версия;
несуществующее имя не подменяется похожим. Проверьте вариант с отсутствующей
в пакете версией. `--detail full` возвращает сохранённую запись, не исходный HTML.
Если нужного поля нет, это остаётся неподтверждённым фактом.

## 4. Конфигурация и выбор цели

```sh
python3 scripts/onec_context.py ensure --workspace-root /path/to/project --need metadata --source-path /path/to/ConfigDump
python3 scripts/onec_context.py resolve-packs --workspace-root /path/to/project --role metadata --all-targets
```

Выберите идентификатор из результата и передайте его в `query-kb --target`.
Ожидание: данные разных конфигураций не смешаны. Для поведения подготовьте
`code`, для точного файла при необходимости `full`. После правок исходников
используйте `init` с соответствующим профилем: `status` не сравнивает все BSL/XML.

## 5. Переносимый пакет

```sh
python3 scripts/onec_context.py export --workspace-root /path/to/project --output-dir /path/to/export --archive
```

Из корня полученного пакета:

```sh
python3 tools/resolve_packs.py --bundle-dir .
python3 tools/verify_local_kb.py --artifacts-dir ./artifacts
```

Ожидание: пути разрешаются внутри пакета, чтение не требует исходного проекта.
Окружение Python должно быть подготовлено заранее. Пакет не содержит сборщика.
Отсутствующий слой нужно подготовить с помощью toolkit и экспортировать заново.

## 6. Проверки и измерения

```sh
python3 -m unittest discover -s tests -v
python3 scripts/onec_context.py verify --workspace-root /path/to/project
python3 scripts/onec_context.py benchmark --workspace-root /path/to/project --loops 3
```

Отдельно измеряйте сборку, первое чтение с распаковкой, повторные запросы и
запуск отдельного процесса CLI. Записывайте версию платформы, состав пакета,
среду и промахи поиска. Ограниченный набор запросов не доказывает охват всего
языка. `verify` не заменяет диагностику и тесты написанного кода 1С.
