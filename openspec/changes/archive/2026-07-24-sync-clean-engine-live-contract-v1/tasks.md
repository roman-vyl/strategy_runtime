## 1. Engine DTO Contract

- [x] 1.1 Remove `instance_id` from live-entry and open-trade Engine request DTOs.
- [x] 1.2 Replace live-entry response fields with `plans_by_side`.
- [x] 1.3 Remove all request echo fields from both Engine response DTOs.
- [x] 1.4 Preserve the existing calculation inputs, open-trade receipt, and recipe models.

## 2. Scalar Router Mapping

- [x] 2.1 Remove Engine `instance_id` request mapping from both routing branches.
- [x] 2.2 Map live-entry `plans_by_side` to the unchanged long/short `EntryRecipe`.
- [x] 2.3 Remove `_validate_echo()` and `EngineResponseBindingError`.
- [x] 2.4 Preserve pre-call Runtime identity-chain validation and source-object binding.

## 3. Contract Verification

- [x] 3.1 Update live and open-trade fake Engine fixtures for calculation-only responses.
- [x] 3.2 Remove echo-mismatch tests and add strict rejection tests for old echo-bearing responses.
- [x] 3.3 Verify Engine requests contain no `instance_id` while Runtime and ABI identities remain intact.
- [x] 3.4 Verify each projection retains the exact source Runtime instance.

## 4. Documentation and Validation

- [x] 4.1 Update Runtime System Plans and main use-case-router spec to the cleaned Engine contract.
- [x] 4.2 Run full pytest, Ruff, mypy, compileall, and strict OpenSpec validation.
