## Context

Call chain per closed bar: `StrategyRuntimeOrchestrator.process()` → `StrategyUseCaseRouter` →
`Engine.project_live_entry` → `EntryReconciliationOrchestrator.execute(projection)` → pure decision →
`NoOp | Apply | Cancel | Replace` → command builder → pending-entry-recovery marker → ABI bridge → confirmation → state
applier. After the first fill the router sends the cycle to Position Management (`frozen_entry_context` set), so entry
reconciliation never sees a filled cycle.

`live_entry_mode` is already in `RuntimeConfig` (`runtime-live-entry-mode-config-v1`) and read by nobody.

## Decisions

- **Naming.** The new policy is `touch_trigger_entry_reconciliation`. The word "frozen" stays out of code identifiers:
  `frozen_entry_context` already means the context of an executed (filled) entry.
- **Separate pure function, old one untouched.** `decide_entry_reconciliation` keeps its exact code and contract
  (`ema_anchor`). The new function lives in the same module, takes the same two inputs, returns the same closed decision
  types and keeps the same fail-closed invariant: it raises `EntryReconciliationInvariantError` when
  `current_trade_cycle.frozen_entry_context` is set.
- **Decision table (touch_trigger).**

  | current cycle | Engine projection | decision |
  |---|---|---|
  | none | none | NoOp |
  | none | DesiredEntry | Apply(DesiredEntry) |
  | acknowledged entry | none | NoOp |
  | acknowledged entry | equal plan | NoOp |
  | acknowledged entry | different plan | NoOp |

  Signals received while the order is held are not remembered.
- **Selection in the orchestrator only.** `EntryReconciliationOrchestrator.__init__` gets a keyword
  `live_entry_mode: LiveEntryMode = "ema_anchor"`, validated against `LIVE_ENTRY_MODES` at construction. `execute` calls
  the function chosen by the mode; everything after the decision is the same code for both modes. There is no second
  execution path and no bypass of `pending_entry_recovery` (a `NoOp` never builds a command or saves a marker, exactly as
  today).
- **Composition.** `bootstrap/application.py` passes `config.live_entry_mode` to `EntryReconciliationOrchestrator` and to
  nothing else.
- **State.** No new fields, no codec change. The held plan is `applied_entry_package.applied_desired_entry` and the
  identity is `trade_cycle_id`, both already persisted.

## Risks

- A held order has no expiry until step 2: `touch_trigger` must not be enabled on a trading stack before step 2 is merged
  and deployed.
- `runtime-live-entry-mode-config-v1` (not archived) states that no behaviour depends on the mode. This change makes
  entry reconciliation depend on it; archive the config change first and this one after it.
- Engine and Runtime config files can disagree. With Engine `ema_anchor` and Runtime `touch_trigger`, Runtime would hold
  the first anchor plan of a cycle. Operating rule: switch both files together.
