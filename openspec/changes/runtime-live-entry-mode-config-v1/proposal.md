## Why

Owner decision 2026-10-28 05:14–05:19 (thread «Перевести вход на цену закрытия свечи касания»): Runtime must become
dual-mode **the same way as Strategy Engine** (strategy_engine #51, `touch-signal-close-entry-v1`): read its own config
file and determine the live-entry mode from it. This change is **infrastructure only**: Runtime reads and keeps the mode;
no Runtime behaviour depends on it yet.

## What Changes

- New Runtime config file, read once at start: path from `RUNTIME_CONFIG_PATH` (in the stack:
  `BBB_data/strategy-runtime/config/runtime.toml`, mounted read-only). Key `live_entry_mode`, values `ema_anchor`
  (default) and `touch_trigger`, the same words as the Engine.
- Unset path, missing file or missing key = `ema_anchor`. An unknown value, an unknown key or a file that does not parse:
  Runtime refuses to start with an error.
- Change = edit the file + restart the Runtime container (no image, no pin, no deploy).
- `RuntimeConfig` carries the resolved `live_entry_mode`. Nothing reads it yet: every Runtime decision, request and
  journal line stays exactly as today in both modes.

## Out of scope

- Any behaviour that differs by mode (order lifetime, order type, ABI contract): later changes, only on the owner's word.
- bbb_stack mount of `${BBB_DATA_ROOT}/strategy-runtime/config` and the env var: separate bbb_stack PR.

## Impact

- `src/strategy_runtime/config/` (loader, model), tests, README.
- Spec `runtime-production-composition`: one added requirement.
