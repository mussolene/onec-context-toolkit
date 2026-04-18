# AGENTS

Этот файл описывает operational workflow для агентов и разработчиков.

## Назначение

Toolkit работает как source-first слой локального 1С context:

- ставит integration layer в `Codex`, `Claude`, `Cursor`
- инициализирует конкретный workspace в `.onec/`
- собирает packs из локальных источников
- проверяет drift по версии платформы и версии конфигурации
- экспортирует runtime bundle из уже собранного workspace
- несёт отдельный supplemental knowledge layer по platform CLI и headless/server workflow
- несёт отдельные supplemental knowledge layers по query strategy, object explanation и platform fact-check

## Архитектурная модель

Один toolkit, несколько слоёв ответственности:

- `runtime/integration`
  - install scripts для `codex`, `claude`, `cursor`
  - общий CLI `scripts/onec_context.py`
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

## Граница знаний

Этот репозиторий не должен превращаться в общую энциклопедию по 1С.

Правило такое:

- `onec-context` отвечает за workspace lifecycle, packs, local query/runtime flow и source-first toolkit behavior
- platform CLI, headless build, cluster/standalone administration и похожие темы можно подключать только как supplemental knowledge layer
- query strategy, object explanation и platform fact-check тоже допустимы как supplemental layers, потому что они усиливают именно локальный toolkit workflow, а не подменяют его
- supplemental layer допустим только если он напрямую помогает build/init/export/headless/admin сценариям этого toolkit
- не смешивать supplemental knowledge с pack model, metadata/code/full runtime contract и базовым `onec-context` skill
- не переносить сюда соседние знания "на всякий случай"; сначала проверить, поддерживают ли они реальные use cases этого repo

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

## Слои

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
5. Если `resolve-packs` возвращает несколько target'ов, выбрать нужный target по имени и версии
6. Делать query/verify/export только после этого

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

## Контракт ответа агента

Если агент отвечает с опорой на toolkit, ответ должен явно содержать:

- `target`
  - какой target выбран; если их несколько и выбор не сделан, это нужно сказать явно
- `used layers`
  - какие слои реально использовались: `platform`, `metadata`, `code`, `full`
- `confirmed facts`
  - только подтверждённые facts из pack/query results или version-exact platform help
- `code-derived inferences`
  - выводы по коду отдельно от facts
- `unresolved assumptions`
  - что осталось недоказанным: не тот слой, не выбран target, неполный source tree, спорная platform claim

Нельзя смешивать подтверждённые факты, inference по коду и недоказанные предположения в один неразмеченный текст.

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

При нескольких target'ах не хардкодить первый попавшийся pack. Нужно либо выбрать target осознанно, либо попросить пользователя уточнить, с какой конфигурацией работать.

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

## Карта репозитория

- `bin/onec-context` — repo-local CLI entrypoint
- `scripts/onec_context.py` — универсальный Python entrypoint; при отсутствии локальной `.venv` сам запускает bootstrap
- `docs/1c-platform-cli.md` — distilled reference по platform CLI и headless/server операциям 1С
- `templates/*skill*.tmpl` и `templates/*rule*.tmpl` — self-contained supplemental guidance layers для агентов
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

## Полный rebuild одного workspace

```bash
onec-context status --workspace-root .
onec-context init --workspace-root . --source-path . --profile full --hbk-base /opt/1cv8 --platform 8.2.19.130
onec-context verify --workspace-root .
onec-context export --workspace-root . --archive
```

<!-- repo-task-proof-loop:start -->
## Repo task proof loop

For substantial features, refactors, and bug fixes, use the repo-task-proof-loop workflow.

Required artifact path:
- Keep all task artifacts in `.agent/tasks/<TASK_ID>/` inside this repository.

Required sequence:
1. Freeze `.agent/tasks/<TASK_ID>/spec.md` before implementation.
2. Implement against explicit acceptance criteria (`AC1`, `AC2`, ...).
3. Create `evidence.md`, `evidence.json`, and raw artifacts.
4. Run a fresh verification pass against the current codebase and rerun checks.
5. If verification is not `PASS`, write `problems.md`, apply the smallest safe fix, and reverify.

Hard rules:
- Do not claim completion unless every acceptance criterion is `PASS`.
- Verifiers judge current code and current command results, not prior chat claims.
- Fixers should make the smallest defensible diff.
- For broad Codex tasks, bounded fan-out is allowed only after `init`, only when the user has explicitly asked for delegation or parallel agent work, and only when task shape warrants it: use bounded `explorer` children before or after spec freeze, use bounded `worker` children only after the spec is frozen, keep the task tree shallow, keep evidence ownership with one builder, and keep verdict ownership with one fresh verifier.
- This root `AGENTS.md` block is the repo-wide Codex baseline. More-specific nested `AGENTS.override.md` or `AGENTS.md` files still take precedence for their directory trees.
- Keep this block lean. If the workflow needs more Codex guidance, prefer nested `AGENTS.md` / `AGENTS.override.md` files or configured fallback guide docs instead of expanding this root block indefinitely.

Installed workflow agents:
- `.codex/agents/task-spec-freezer.toml`
- `.codex/agents/task-builder.toml`
- `.codex/agents/task-verifier.toml`
- `.codex/agents/task-fixer.toml`
<!-- repo-task-proof-loop:end -->
