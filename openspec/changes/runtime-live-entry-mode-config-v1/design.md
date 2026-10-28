## Context

Runtime configuration today is environment-only (`config/loader.py`, `RuntimeConfig`). Strategy Engine (#51) added an
optional TOML file named by an env var, read once at start, with `live_entry_mode`. The owner wants the same mechanism in
Runtime.

## Decisions

- **Same shape as the Engine.** `RUNTIME_CONFIG_PATH` names an optional TOML file; `tomllib` reads it once inside
  `load_runtime_config`. Allowed keys: `{"live_entry_mode"}`. Allowed values: `ema_anchor`, `touch_trigger`.
- **Defaults.** Unset or empty path, or a path to a missing file → `{}` → `ema_anchor`.
- **Fail closed.** Parse error, unknown key, non-string or unknown value → `ValueError` at start (the existing
  configuration gate already stops composition on `ValueError`).
- **Read once.** The value lives in the frozen `RuntimeConfig`; there is no reload. Switching = edit + restart.
- **No consumer.** No component reads `live_entry_mode` in this change, so both modes are behaviourally identical.

## Risks

- Engine and Runtime files can disagree. Harmless now (Runtime ignores the mode); the change that first gives Runtime a
  mode-dependent behaviour decides how to treat a mismatch.
