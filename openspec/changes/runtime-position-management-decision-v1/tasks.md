## 1. Models and State

- [x] 1.1 Add the closed `NoOp` / `ApplyProtection` / `ClosePosition`
  decision variants and their union type.
- [x] 1.2 Add a nullable latest confirmed management protection field to
  `CurrentTradeCycle`, with no history or pending state.

## 2. Decision Logic

- [x] 2.1 Resolve the effective acknowledged protection: latest confirmed
  management protection, else the frozen entry context's initial stop/take.
- [x] 2.2 Implement the pure decision function selecting one variant from a
  `PositionManagementRecipe` and the current trade cycle.
- [x] 2.3 Give an active close signal unconditional priority, regardless
  of whether protection in the same recipe is equal or differs.
- [x] 2.4 Compare protection by exact value equality, no float conversion.
- [x] 2.5 Raise a typed invariant error for a missing/unfrozen current
  trade cycle or a wrong-typed input; produce no decision in that case.

## 3. Verification

- [x] 3.1 Focused unit tests for close priority, protection comparison,
  baseline resolution, diagnostics irrelevance, and invariant failures.
- [x] 3.2 Full test suite, `ruff check`, `ruff format --check`, `mypy`,
  `openspec validate` for this change and `--all`, both `--strict`.
- [ ] 3.3 Sync affected specs and archive this change after approval.
