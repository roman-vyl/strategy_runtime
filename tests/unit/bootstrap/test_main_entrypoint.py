"""Focused tests for the production executable entrypoint."""

from types import SimpleNamespace

import pytest

from strategy_runtime.bootstrap import main as main_module


def test_invalid_configuration_exits_non_zero_and_does_not_start_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "load_runtime_config",
        lambda: (_ for _ in ()).throw(ValueError("invalid config")),
    )
    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        main_module,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: uvicorn_calls.append(kwargs)),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert uvicorn_calls == []


def test_not_ready_application_exits_non_zero_and_does_not_start_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(host="0.0.0.0", port=8093)
    app = SimpleNamespace(state=SimpleNamespace(ready=False))

    monkeypatch.setattr(main_module, "load_runtime_config", lambda: config)
    monkeypatch.setattr(main_module, "build_application", lambda: app)
    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        main_module,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: uvicorn_calls.append(kwargs)),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert uvicorn_calls == []


def test_ready_application_starts_uvicorn_once_with_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(host="0.0.0.0", port=9000)
    app = SimpleNamespace(state=SimpleNamespace(ready=True))
    uvicorn_calls: list[dict[str, object]] = []

    monkeypatch.setattr(main_module, "load_runtime_config", lambda: config)
    monkeypatch.setattr(main_module, "build_application", lambda: app)
    monkeypatch.setattr(
        main_module,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: uvicorn_calls.append(kwargs)),
    )

    main_module.main()

    assert uvicorn_calls == [{"host": "0.0.0.0", "port": 9000}]
