# Strategy Engine contract cleanup plans

These plans are stored in the Strategy Runtime workspace because they describe
required changes to the opposite side of Runtime ↔ Engine contracts.

- `24_trade_id_removal_plan.md`
- `25_engine_spec_hash_contract_cleanup_plan.md`

They are plans for the separate Strategy Engine repository. No Engine code is
implemented from this Runtime repository.

- `26_engine_market_data_hash_contract_cleanup_plan.md` — remove `market_data_hash` from Runtime-facing Engine contracts.
- `27_engine_contract_version_cleanup_plan.md` — remove payload-level `contract_version` from Runtime-facing Engine contracts.

- `29_engine_strategy_version_compatibility_profile_cleanup_plan.md` — remove obsolete strategy implementation/profile selectors from Engine contracts.
