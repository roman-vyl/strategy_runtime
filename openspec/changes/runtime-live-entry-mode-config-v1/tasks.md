## 1. Config

- [x] 1.1 `RuntimeConfig.live_entry_mode` (`ema_anchor` default) with validation
- [x] 1.2 `load_runtime_config` reads the TOML named by `RUNTIME_CONFIG_PATH` once (missing = defaults; bad file, key or value = `ValueError`)
- [x] 1.3 README: file, key, values, restart to switch

## 2. Tests

- [x] 2.1 Loader tests: unset path, missing file, missing key, each valid value, unknown value, unknown key, broken TOML
- [x] 2.2 Targeted existing config / composition tests stay green; ruff and mypy clean
