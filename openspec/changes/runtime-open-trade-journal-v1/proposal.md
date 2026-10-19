## Why

While a position is open, Runtime journals nothing per bar. `trade_cycle_opened` and `trade_cycle_closed` mark the two ends of a cycle, but what Engine asked for on each bar in between (stop, take, close signal) and which protection ABI actually confirmed exist only inside Runtime state. The Central Journal and the Workbench therefore cannot show how a position was managed. The pre-entry side already has this pair: `live_entry_evaluated` (Engine answer on every bar) and `entry_package_applied` (ABI-confirmed order values). This change adds the same pair for the open-trade side, as close a copy of the pre-entry pattern as the code allows.

## What Changes

- New journal event `open_trade_evaluated`: one record for every successful Engine open-trade answer, written right after routing and before position management runs, NoOp bars included. Payload: `instrument`, `timeframe`, `bar_open_time_ms`, `trade_cycle_id`, `side`, `desired_protection {stop_price, take_price}`, `close_signal {active, reason, component_id, layer}`. No Engine diagnostics (symmetry with `live_entry_evaluated`).
- New journal event `protection_applied`: one record for every ABI-confirmed protection change, written in `PositionManagementOrchestrator` after ABI confirms and before the confirmation is applied to state (copy of `entry_package_applied`). Payload: `trade_cycle_id`, `bar_open_time_ms`, `stop_price`, `take_price`, plus the two concrete protective orders on the exchange, `stop_order` and `take_order`, each `{order_id, trigger_price, quantity}` as ABI read them back.
- **BREAKING (contract):** the ABI protection success body gains a required `protection_orders` object (`stop`, `take`, each `order_id`, `trigger_price`, `quantity`). ABI already reads both orders back after every protection write but does not return them today. Runtime decodes them strictly; old ABI bodies are rejected, so Runtime and ABI are deployed together. The ABI side is its own OpenSpec.
- Two optional journal ports, two `ProcessingJournalEventType` members, two JSONL adapter methods, production wiring.
- No change to the Engine contract, position management decisions, Runtime state or recovery. Exit price and time are out of scope (separate change). Journal service ingestion and Workbench display are separate later OpenSpecs.

## Capabilities

### Modified Capabilities

- `processing-journal`: `open_trade_evaluated` and `protection_applied` events.
- `strategy-runtime-orchestrator`: journals every successful open-trade evaluation.
- `position-management-orchestrator`: journals every ABI-confirmed protection.
- `abi-position-management-client`: required `protection_orders` in the protection success body.
- `runtime-production-composition`: wires the JSONL journal into both ports.

## Impact

`runtime/orchestrator/ports.py`, `runtime/orchestrator/orchestrator.py`, `runtime/position_management_orchestrator/ports.py`, `runtime/position_management_orchestrator/orchestrator.py`, `infrastructure/abi/position_management_codec.py`, `runtime/position_management_execution/models.py`, `utility/processing_journal` (event types and adapter), `bootstrap/application.py`, tests. ABI emits `protection_orders` in its own change; Journal service and frontend follow in their own changes.
