# Strategy Runtime

`Strategy Runtime` — live orchestration service в составе BBB. Он получает от Market Data Service уведомления о закрытых барах, находит затронутые strategy instances, проверяет через ABI состояние уже зарегистрированного trade cycle, выбирает нужный calculation path в Strategy Engine и передаёт подтверждаемые execution-команды в ABI Executor Bot.

Runtime владеет live lifecycle state каждого `strategy_instance_id`. При этом он не рассчитывает индикаторы, не содержит торговую стратегию, не обращается к бирже напрямую и не является хранилищем market data.

## Место Runtime в системе

```text
Market Data Service
        |
        | closed bar
        v
Strategy Runtime
        |
        +------> Strategy Engine
        |          calculation
        |
        +------> ABI Executor Bot
                    execution
                       |
                       v
                     Bybit
```

MDS сообщает факт закрытия бара. Strategy Engine рассчитывает желаемое состояние стратегии. Runtime оркестрирует live lifecycle и хранит подтверждённое состояние strategy instance. ABI отвечает за exchange-facing execution и получает факты позиции от биржи.

## Архитектура Runtime

Основной вход — быстрый closed-bar webhook. После принятия события дальнейшая обработка идёт в одном background worker:

```text
MDS closed-bar webhook
        |
        v
FastAPI ingress
        |
        v
CommittedBarIntakeBoundary          bounded process-local FIFO
        |
        v
CommittedBarIntakeWorker            exactly one consumer
        |
        v
CommittedBarOrchestrator
        | deployment catalog
        | selector
        | deterministic per-instance fan-out
        v
StrategyRuntimeOrchestrator.dispatch()
        | keyed mutex for strategy_instance_id
        | get-or-create Runtime state
        | ABI position resolution for an existing cycle
        | first-fill freeze before routing when position is open
        v
StrategyUseCaseRouter
        |
        +-----------------------------+-----------------------------+
        |                                                           |
        | NO OPEN POSITION                                      OPEN POSITION
        v                                                           v
Engine live-entry                                          frozen entry context
        |                                                           |
        v                                                           v
EntryReconciliationOrchestrator                         Engine open-trade
        |                                                           |
        v                                                           v
ABI entry-package                                  PositionManagementOrchestrator
        |                                                           |
        |                                                           v
        |                                                ABI protection / close
        |                                                           |
        +-----------------------------+-----------------------------+
                                      |
                                      v
                           resulting Runtime state
                                      |
                                      v
                           post-projection save
                             only when changed
```

На open-position path первый обнаруженный fill фиксируется до вызова `StrategyUseCaseRouter`. Поэтому Engine open-trade всегда получает уже frozen entry context. Router выбирает только один из двух Engine paths; торговое решение остаётся внутри Strategy Engine.

## Отдельный first-fill callback

ABI может сообщить first fill независимо от прихода market bar. Это другой синхронный inbound path, не связанный с intake queue:

```text
ABI first-fill callback
        |
        v
FastAPI
        |
        v
AbiExecutionEventOrchestrator
        |
        v
same keyed mutex
        |
        v
same Runtime repository
        |
        v
first-fill state transition
```

`StrategyRuntimeOrchestrator` и `AbiExecutionEventOrchestrator` получают один и тот же `StrategyInstanceKeyedMutexRegistry` и один и тот же `InMemoryStrategyInstanceRuntimeStateRepository`. Closed-bar processing и ABI callback не могут одновременно изменять состояние одного `strategy_instance_id`. Повтор того же first-fill идемпотентен; противоречащий timestamp отклоняется без изменения state.

## Один closed-bar cycle по шагам

### 1. Closed-bar ingress

MDS отправляет `POST /v1/webhooks/closed-bar` с `instrument`, `timeframe` и `open_time_ms`. FastAPI валидирует transport shape, создаёт `CommittedBarEvent` и неблокирующе помещает его в bounded queue.

HTTP `200 {"status":"accepted"}` означает только принятие события в очередь. Он не означает, что Engine завершил расчёт, ABI подтвердил действие или биржа исполнила ордер. Неготовый Runtime, остановленная или заполненная очередь отвечают `503` до принятия события.

### 2. Intake queue and worker

`CommittedBarIntakeBoundary` владеет единственной process-local FIFO queue с настраиваемой ёмкостью. Один `CommittedBarIntakeWorker` последовательно извлекает события и вызывает `CommittedBarOrchestrator.process()`.

Ошибка одного события записывается через logging/journal path и не завершает worker. Одновременно выполняется не более одного принятого closed-bar event.

### 3. Deployment selection

`FilesystemDeploymentCatalog` читает flat JSON deployment files из `RUNTIME_SPECS_PATH`. `CommittedBarDeploymentSelector` оставляет enabled deployments с точным совпадением `ticker` и `base_timeframe` входного бара.

Для каждого совпадения создаётся `StrategyBarProcessingUnit`. Units передаются напрямую в `StrategyRuntimeOrchestrator.dispatch()` последовательно, в детерминированном порядке по `strategy_instance_id`. Один неуспешный instance становится failed outcome, но не отменяет обработку остальных instances этого бара.

### 4. Strategy Runtime cycle

`StrategyRuntimeOrchestrator` захватывает keyed mutex до чтения state и держит его до завершения всей обработки instance: repository, ABI lookup, Engine, nested orchestrator и необходимые saves находятся внутри одной critical section.

Repository возвращает существующий `StrategyInstanceRuntimeState` либо создаёт его из принятого deployment snapshot. Runtime не допускает одновременных state writers для одного instance, но разные ключи не блокируют друг друга на уровне mutex registry.

### 5. Position resolution

`OpenPositionResolver` проверяет authoritative position fact через ABI только если state уже содержит `CurrentTradeCycle`. Запрос адресуется парой `strategy_instance_id` + `trade_cycle_id`.

Если `CurrentTradeCycle` отсутствует, Runtime локально получает `position_open=false` и не вызывает ABI: в рамках текущего in-memory lifecycle ещё нет Runtime-issued entry package, который можно было бы проверить.

### 6. The fork

`StrategyUseCaseRouter` получает processing unit вместе с resolved state и выбирает ровно один path:

- `position_open=false` → Engine live-entry;
- `position_open=true` → Engine open-trade.

Для open position верхний orchestrator сначала применяет first-fill transition. При первом наблюдении он фиксирует entry context отдельным immediate save и только затем вызывает Router.

### 7A. Live-entry branch

```text
Runtime
  -> Engine live-entry
  -> desired_entry
  -> EntryReconciliationOrchestrator
  -> ABI entry-package
  -> confirmed Runtime state
```

Engine возвращает `desired_entry` либо `null`. Runtime сравнивает результат с текущим cycle и получает `NoOp`, `Apply`, `Replace` или `Cancel`. Для command-bearing решения `EntryReconciliationOrchestrator` строит команду и передаёт её через `AbiEntryPackageExecutionBridge` в ABI.

Новый `CurrentTradeCycle`, замена entry package или удаление cycle появляются в Runtime state только после подходящей ABI confirmation. Engine projection сама по себе state не изменяет.

### 7B. Open-trade branch

```text
first-fill freeze
  -> Engine open-trade
  -> desired protection / close signal
  -> PositionManagementOrchestrator
  -> ABI protection / close
  -> confirmed Runtime state
```

Engine получает immutable entry context: применённый `DesiredEntry` и время entry bar, нормализованное по сетке базового timeframe. Вместе с текущим target bar этого достаточно для open-trade calculation; детали формирования frozen context остаются внутренней ответственностью Runtime.

`PositionManagementOrchestrator` выбирает `NoOp`, `ApplyProtection` или `ClosePosition`. Protection становится частью state только после совпадающей ABI confirmation; подтверждённый close очищает текущий cycle. Transport или protocol failure не превращается в успешный state transition.

### 8. Persistence

После любой semantic branch верхний orchestrator сравнивает `resulting_state` с source state, вложенным в projection:

- value-equal state не сохраняется;
- изменённый aggregate получает один post-projection `repository.save()`;
- command result применяется только после ABI confirmation;
- первый обнаруженный fill может иметь отдельный immediate save.

Следовательно, один open-position cycle может выполнить два save: first-fill freeze, затем подтверждённый post-projection transition. Это две разные подтверждённые границы, а не дублирование записи.

## State model

### `StrategyInstanceRuntimeState`

Главный immutable aggregate одного live strategy instance. Он хранит identity, registered deployment snapshot, `risk_multiplier` и optional текущий cycle. Repository владеет единственной актуальной версией aggregate для каждого `strategy_instance_id`.

### `CurrentTradeCycle`

Runtime-owned lifecycle текущего entry/position: opaque `trade_cycle_id`, подтверждённый `AppliedEntryPackage`, optional frozen entry context и последняя подтверждённая management protection. Наличие cycle само по себе не доказывает, что exchange position сейчас открыта — этот факт сообщает ABI.

### Frozen entry context

После первого подтверждённого fill Runtime один раз фиксирует применённый `DesiredEntry`, точный `first_fill_at_ms` и начало соответствующего entry bar. Open-trade calculation использует этот immutable контекст, а не новый live-entry расчёт.

### Confirmed protection

Runtime хранит только последнюю подтверждённую ABI management protection, без истории и промежуточного execution state. Close confirmation удаляет `CurrentTradeCycle` целиком.

> Runtime state представляет подтверждённую live lifecycle truth, а не просто последний желаемый расчёт Engine.

## Владение ответственностями

| Concern | Owner |
|---|---|
| candles / market history | Market Data Service |
| strategy calculations | Strategy Engine |
| live orchestration | Strategy Runtime |
| per-instance live lifecycle state | Strategy Runtime |
| exchange execution | ABI Executor Bot |
| exchange position truth | ABI / exchange |
| synchronization of Runtime writers | Strategy Runtime |

## Основные orchestrators

| Component | Responsibility | Path |
|---|---|---|
| `CommittedBarOrchestrator` | catalog → selection → per-instance dispatch и journal outcomes | closed-bar |
| `StrategyRuntimeOrchestrator` | один locked strategy cycle от state load до conditional save | closed-bar |
| `EntryReconciliationOrchestrator` | live-entry decision → ABI confirmation → aggregate | no-open-position branch |
| `PositionManagementOrchestrator` | protection/close decision → ABI confirmation → aggregate | open-position branch |
| `AbiExecutionEventOrchestrator` | first-fill callback → idempotent state transition | separate inbound callback |

`EntryReconciliationOrchestrator` и `PositionManagementOrchestrator` — соседние semantic branches. На одном cycle вызывается только один из них; persistence остаётся ответственностью `StrategyRuntimeOrchestrator`.

## HTTP surface

Inbound HTTP Runtime:

```text
GET  /health/live
GET  /health/ready
POST /v1/webhooks/closed-bar
PUT  /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill
```

Closed-bar webhook подтверждает помещение события в очередь. First-fill endpoint синхронно ждёт применения transition под mutex. Readiness отражает успешную startup composition, но не проверяет доступность Engine, ABI, market stream или состояние позиции.

Outbound relationships:

| Direction | Operation | HTTP |
|---|---|---|
| Runtime → Strategy Engine | live-entry calculation | `POST /v1/strategy-evaluations/live-entry` |
| Runtime → Strategy Engine | open-trade calculation | `POST /v1/strategy-evaluations/open-trade` |
| Runtime → ABI | open-position lookup | `GET .../open-position` |
| Runtime → ABI | entry-package apply/replace/cancel | `PUT .../entry-package` |
| Runtime → ABI | protection | `PUT .../protection` |
| Runtime → ABI | close position | `DELETE .../open-position` |

Полные wire schemas здесь не дублируются. Runtime capability contracts лежат в [`openspec/specs/`](openspec/specs), executable client contracts — в [`tests/contract/`](tests/contract), а ABI OpenAPI authority проверяется там же по документам соседнего `abi_executor_bot/docs/openapi/`.

## Concurrency и operational boundaries V1

- Runtime state хранится в одном `InMemoryStrategyInstanceRuntimeStateRepository` и теряется при restart.
- Closed-bar intake — bounded process-local FIFO; принятые, но не завершённые события не переживают restart и не восстанавливаются из JSONL journal.
- Очередь обслуживает ровно один `CommittedBarIntakeWorker`; worker count не настраивается.
- Keyed mutex сериализует closed-bar cycle и first-fill callback одного `strategy_instance_id` только внутри процесса.
- Production topology V1 — один process, один worker и одна replica. Между процессами нет distributed lock, repository CAS или другой координации.
- Каждый outbound HTTP adapter выполняет одну bounded попытку без retry и без follow redirects. Автоматического recovery workflow нет.
- JSONL processing journal фиксирует orchestration outcomes, но не является durable queue или state repository.

Это operational boundary текущего V1: безопасное продолжение stateful lifecycle после потери процесса не заявляется.

## Configuration

Полный environment surface и рабочие примеры значений находятся в [`config/runtime.env.example`](config/runtime.env.example).

Runtime:

- `RUNTIME_HOST`, `RUNTIME_PORT` — bind address;
- `RUNTIME_SPECS_PATH` — flat deployment catalog;
- `RUNTIME_JOURNAL_PATH` — JSONL processing journal;
- `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` — ёмкость intake queue.

Strategy Engine:

- `RUNTIME_STRATEGY_ENGINE_BASE_URL`;
- `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`.

ABI:

- `RUNTIME_ABI_BASE_URL`;
- `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`;
- `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`;
- `RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS`.

Все base URLs и timeouts обязательны для ready application. Host, port, specs path и journal path имеют локальные defaults; queue capacity обязательна.

## Запуск и проверка

Проект требует Python `>=3.12,<3.13`; repository workflow использует `python3.12` и локальную `.venv`.

```bash
make install-dev
make run
make verify
```

`make install-dev` создаёт `.venv` и устанавливает package с dev dependencies. `make run` запускает единственный production composition root через Uvicorn. `make verify` выполняет Ruff lint, Ruff format check, mypy и pytest.

Строгая проверка canonical OpenSpec запускается отдельно:

```bash
npm exec -- openspec validate --all --strict
```

## Карта репозитория

```text
src/strategy_runtime/
├── adapters/          inbound HTTP adapters
├── bootstrap/         production composition root and executable entrypoint
├── config/            environment model, loader and startup path checks
├── infrastructure/    concrete Engine and ABI HTTP adapters
├── runtime/           live state, routing and semantic orchestration
├── shared/            small cross-cutting value helpers
└── utility/           deployment selection, bar fan-out and journal
```

## Куда смотреть дальше

- Current capability contracts: [`openspec/specs/`](openspec/specs)
- Completed historical changes: [`openspec/changes/archive/`](openspec/changes/archive)
- Environment source of truth: [`config/runtime.env.example`](config/runtime.env.example)
- HTTP/client contracts: [`tests/contract/`](tests/contract)
- Production path integration: [`tests/integration/`](tests/integration)
- Component behavior and architecture guards: [`tests/unit/`](tests/unit)
