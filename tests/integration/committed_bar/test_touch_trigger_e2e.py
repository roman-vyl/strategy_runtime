"""Vertical E2E checks of the touch_trigger entry policy (runtime-frozen-entry-integration-v1).

The same production composition and fake Engine/ABI HTTP servers as
`test_production_e2e.py`, with a Runtime config file selecting
`live_entry_mode = "touch_trigger"` and `order_lifetime_bars = 3`. The fake
Engine behaves like the touch_trigger Engine: it returns a plan only for the
signal bars a test names, planned on the requested bar, and `null` otherwise.

Timeline used throughout (5m bars, N = 3): the signal bar opens at `S`; the
entry is applied while processing it, held on bars S+1..S+3, and expires on
bar S+4 (its close reaches S + (N + 2) * 5m).
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.bootstrap.application import build_application

from ._fake_http_server import FakeHttpServer, FakeResponse, RecordedRequest, route
from .test_production_e2e import (
    _LIVE_ENTRY_PATH,
    _OPEN_TRADE_PATH,
    _STRATEGY_INSTANCE_ID,
    _dispatch_outcomes,
    _entry_package_absent,
    _entry_package_applied,
    _open_position_closed,
    _open_position_open,
    _open_trade_success,
    _parse_entry_package_path,
    _post_closed_bar,
    _set_abi_routes,
    _set_engine_routes,
    _synchronize_committed_bar_processing,  # noqa: F401  (autouse fixture)
    _write_deployment,
)

TF = 300_000
S = 1_720_000_200_000  # a 5m boundary
EXPIRY_BAR = S + 4 * TF
_SLOW_ABI_SECONDS = 1.5
_ABI_ENTRY_PACKAGE_TIMEOUT = 0.5


@pytest.fixture
def engine_server() -> Iterator[FakeHttpServer]:
    server = FakeHttpServer(route({}, not_found=FakeResponse(404, {"error": "not_found"})))
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def abi_server() -> Iterator[FakeHttpServer]:
    server = FakeHttpServer(route({}, not_found=FakeResponse(404, {"error": "not_found"})))
    try:
        yield server
    finally:
        server.close()


def _bar(index: int) -> int:
    return S + index * TF


def _build_app(
    tmp_path: Path,
    *,
    engine_base_url: str,
    abi_base_url: str,
    config_text: str | None = 'live_entry_mode = "touch_trigger"\norder_lifetime_bars = 3\n',
    abi_entry_package_timeout: float = 5.0,
):
    _write_deployment(tmp_path / "specs")
    env = {
        "RUNTIME_SPECS_PATH": str(tmp_path / "specs"),
        "RUNTIME_JOURNAL_PATH": str(tmp_path / "journal" / "runtime.jsonl"),
        "RUNTIME_STATE_PATH": str(tmp_path / "state" / "runtime_state.jsonl"),
        "RUNTIME_STRATEGY_ENGINE_BASE_URL": engine_base_url,
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_BASE_URL": abi_base_url,
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS": str(abi_entry_package_timeout),
        "RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS": "5",
        "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": "256",
    }
    if config_text is not None:
        config_path = tmp_path / "runtime.toml"
        config_path.write_text(config_text, encoding="utf-8")
        env["RUNTIME_CONFIG_PATH"] = str(config_path)
    return build_application(env)


def _plan_wire(bar_open_time_ms: int, *, price: str = "100") -> dict[str, object]:
    return {
        "side": "long",
        "source_plan_bar_open_time_ms": bar_open_time_ms,
        "planned_entry_price": price,
        "initial_stop_price": "90",
        "initial_take_price": "120",
        "locked_exit_profile": "standard",
    }


def _touch_engine(
    signal_bars: set[int], *, price: str = "100"
) -> Callable[[RecordedRequest], FakeResponse]:
    """A touch_trigger Engine: a plan on the named signal bars only."""

    def handle(request: RecordedRequest) -> FakeResponse:
        target = request.json()["target_bar_open_time_ms"]
        if target in signal_bars:
            return FakeResponse(200, {"desired_entry": _plan_wire(target, price=price)})
        return FakeResponse(200, {"desired_entry": None})

    return handle


def _slow_abi(_request: RecordedRequest) -> FakeResponse:
    return FakeResponse(200, {}, delay_seconds=_SLOW_ABI_SECONDS)


def _scripted(*handlers: Callable[[RecordedRequest], FakeResponse]):
    """Answer the Nth entry-package call with the Nth handler (the last one repeats)."""
    calls = [0]

    def handle(request: RecordedRequest) -> FakeResponse:
        index = min(calls[0], len(handlers) - 1)
        calls[0] += 1
        return handlers[index](request)

    return handle


def _entry_package_requests(server: FakeHttpServer) -> list[RecordedRequest]:
    return [r for r in server.requests if "/entry-package" in r.path]


def _live_entry_requests(server: FakeHttpServer) -> list[RecordedRequest]:
    return [r for r in server.requests if r.path == _LIVE_ENTRY_PATH]


def _state(app):
    state = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
    assert state is not None
    return state


def _cycle_id(app) -> str:
    cycle = _state(app).current_trade_cycle
    assert cycle is not None
    return cycle.trade_cycle_id


def _held_plan_bar(app) -> int:
    cycle = _state(app).current_trade_cycle
    assert cycle is not None
    return cycle.applied_entry_package.applied_desired_entry.source_plan_bar_open_time_ms


# --- 1. Apply -> held -> fill -> Position Management --------------------------


def test_held_entry_fills_and_moves_to_position_management(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(
        engine_server,
        live_entry=_touch_engine({S, _bar(1)}),
        open_trade=_open_trade_success(),
    )
    open_position = _scripted(
        lambda _r: _open_position_closed(),
        lambda _r: _open_position_open(_bar(2), "100"),
    )
    _set_abi_routes(abi_server, open_position=open_position, entry_package=_entry_package_applied)
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        cycle_id = _cycle_id(app)
        # A new signal on S+1 is ignored while the entry is held.
        _post_closed_bar(client, _bar(1))
        assert _cycle_id(app) == cycle_id
        _post_closed_bar(client, _bar(2))

        state = _state(app)
        assert state.current_trade_cycle is not None
        assert state.current_trade_cycle.trade_cycle_id == cycle_id
        assert state.current_trade_cycle.frozen_entry_context is not None
        assert [r.json()["desired_entry"] for r in _entry_package_requests(abi_server)] == [
            _plan_wire(S)
        ]
        assert len([r for r in engine_server.requests if r.path == _OPEN_TRADE_PATH]) == 1


# --- 2. Apply -> held -> expiry -> Cancel ------------------------------------


def test_held_entry_is_cancelled_exactly_on_the_expiry_bar(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_touch_engine({S, _bar(2)}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(_entry_package_applied, _entry_package_absent),
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        cycle_id = _cycle_id(app)
        for index in (1, 2, 3):
            _post_closed_bar(client, _bar(index))
            assert _cycle_id(app) == cycle_id
            assert _held_plan_bar(app) == S
            assert len(_entry_package_requests(abi_server)) == 1

        _post_closed_bar(client, EXPIRY_BAR)

        state = _state(app)
        assert state.current_trade_cycle is None
        assert state.pending_entry_recovery is None
        requests = _entry_package_requests(abi_server)
        assert [r.json()["desired_entry"] for r in requests] == [_plan_wire(S), None]
        assert _parse_entry_package_path(requests[1].path)[1] == cycle_id
        # The Engine was asked on every bar, as in ema_anchor.
        assert len(_live_entry_requests(engine_server)) == 5


# --- 3. Apply -> held -> expiry -> Replace -----------------------------------


def test_held_entry_is_replaced_on_the_expiry_bar_and_gets_a_new_lifetime(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    # Same prices on the expiry bar: still a Replace (a new signal, a new lifetime).
    _set_engine_routes(engine_server, live_entry=_touch_engine({S, EXPIRY_BAR}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(
            _entry_package_applied,
            _entry_package_absent,
            _entry_package_applied,
            _entry_package_absent,
        ),
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        old_cycle_id = _cycle_id(app)
        for index in (1, 2, 3, 4):
            _post_closed_bar(client, _bar(index))
        new_cycle_id = _cycle_id(app)
        assert new_cycle_id != old_cycle_id
        assert _held_plan_bar(app) == EXPIRY_BAR
        assert _state(app).pending_entry_recovery is None

        # The new lifetime counts from the new signal bar: held on S+5..S+7,
        # cancelled on S+8.
        for index in (5, 6, 7):
            _post_closed_bar(client, _bar(index))
            assert _cycle_id(app) == new_cycle_id
        _post_closed_bar(client, _bar(8))

        assert _state(app).current_trade_cycle is None
        requests = _entry_package_requests(abi_server)
        assert [r.json()["desired_entry"] for r in requests] == [
            _plan_wire(S),
            None,
            _plan_wire(EXPIRY_BAR),
            None,
        ]
        assert [_parse_entry_package_path(r.path)[1] for r in requests] == [
            old_cycle_id,
            old_cycle_id,
            new_cycle_id,
            new_cycle_id,
        ]


# --- 4. ABI timeouts -> existing pending entry recovery ----------------------


def _assert_next_bar_is_deferred(
    client: TestClient,
    app,
    engine_server: FakeHttpServer,
    abi_server: FakeHttpServer,
    bar_open_time_ms: int,
) -> None:
    before_state = _state(app)
    engine_calls = len(_live_entry_requests(engine_server))
    abi_calls = len(abi_server.requests)
    _post_closed_bar(client, bar_open_time_ms)
    # The recovery guard stops the bar before ABI and Engine: no reconciliation.
    assert _state(app) == before_state
    assert len(_live_entry_requests(engine_server)) == engine_calls
    assert len(abi_server.requests) == abi_calls


def test_apply_timeout_leaves_the_recovery_marker_and_defers_later_bars(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_touch_engine({S, _bar(1)}))
    _set_abi_routes(abi_server, open_position=_open_position_closed(), entry_package=_slow_abi)
    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        abi_entry_package_timeout=_ABI_ENTRY_PACKAGE_TIMEOUT,
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        state = _state(app)
        assert state.current_trade_cycle is None
        assert state.pending_entry_recovery is not None
        (apply_request,) = _entry_package_requests(abi_server)
        assert (
            _parse_entry_package_path(apply_request.path)[1]
            == state.pending_entry_recovery.trade_cycle_id
        )
        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_failed"

        _assert_next_bar_is_deferred(client, app, engine_server, abi_server, _bar(1))


def test_expiry_cancel_timeout_leaves_the_recovery_marker_on_the_held_cycle(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_touch_engine({S}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(_entry_package_applied, _slow_abi),
    )
    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        abi_entry_package_timeout=_ABI_ENTRY_PACKAGE_TIMEOUT,
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        cycle_id = _cycle_id(app)
        for index in (1, 2, 3, 4):
            _post_closed_bar(client, _bar(index))

        state = _state(app)
        assert state.current_trade_cycle is not None
        assert state.current_trade_cycle.trade_cycle_id == cycle_id
        assert state.pending_entry_recovery is not None
        assert state.pending_entry_recovery.trade_cycle_id == cycle_id
        assert [r.json()["desired_entry"] for r in _entry_package_requests(abi_server)] == [
            _plan_wire(S),
            None,
        ]

        _assert_next_bar_is_deferred(client, app, engine_server, abi_server, _bar(5))


def test_replace_cancel_phase_timeout_sends_no_apply(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_touch_engine({S, EXPIRY_BAR}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(_entry_package_applied, _slow_abi, _entry_package_applied),
    )
    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        abi_entry_package_timeout=_ABI_ENTRY_PACKAGE_TIMEOUT,
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        old_cycle_id = _cycle_id(app)
        for index in (1, 2, 3, 4):
            _post_closed_bar(client, _bar(index))

        state = _state(app)
        # The CANCEL phase timed out: the old cycle and its marker stay; no APPLY was sent.
        assert state.current_trade_cycle is not None
        assert state.current_trade_cycle.trade_cycle_id == old_cycle_id
        assert state.pending_entry_recovery is not None
        assert state.pending_entry_recovery.trade_cycle_id == old_cycle_id
        assert [r.json()["desired_entry"] for r in _entry_package_requests(abi_server)] == [
            _plan_wire(S),
            None,
        ]

        _assert_next_bar_is_deferred(client, app, engine_server, abi_server, _bar(5))


def test_replace_apply_phase_timeout_leaves_the_new_cycle_marker(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_touch_engine({S, EXPIRY_BAR}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(_entry_package_applied, _entry_package_absent, _slow_abi),
    )
    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        abi_entry_package_timeout=_ABI_ENTRY_PACKAGE_TIMEOUT,
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        old_cycle_id = _cycle_id(app)
        for index in (1, 2, 3, 4):
            _post_closed_bar(client, _bar(index))

        state = _state(app)
        # CANCEL confirmed, the APPLY timed out: the boundary save left no
        # cycle and a marker for the new identity the APPLY was sent with.
        assert state.current_trade_cycle is None
        assert state.pending_entry_recovery is not None
        requests = _entry_package_requests(abi_server)
        assert [r.json()["desired_entry"] for r in requests] == [
            _plan_wire(S),
            None,
            _plan_wire(EXPIRY_BAR),
        ]
        new_cycle_id = _parse_entry_package_path(requests[2].path)[1]
        assert new_cycle_id != old_cycle_id
        assert state.pending_entry_recovery.trade_cycle_id == new_cycle_id

        _assert_next_bar_is_deferred(client, app, engine_server, abi_server, _bar(5))


# --- 5. Restart with a held entry --------------------------------------------


def test_restart_keeps_the_held_entry_and_its_original_expiry(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_touch_engine({S, _bar(3)}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(_entry_package_applied, _entry_package_absent),
    )
    first_app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )
    with TestClient(first_app) as client:
        _post_closed_bar(client, S)
        _post_closed_bar(client, _bar(1))
        cycle_id = _cycle_id(first_app)

    second_app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )
    with TestClient(second_app) as client:
        assert _cycle_id(second_app) == cycle_id
        assert _held_plan_bar(second_app) == S
        # Held through the restart; the S+3 signal does not extend the lifetime.
        for index in (2, 3):
            _post_closed_bar(client, _bar(index))
            assert _cycle_id(second_app) == cycle_id
        _post_closed_bar(client, EXPIRY_BAR)

        assert _state(second_app).current_trade_cycle is None
        requests = _entry_package_requests(abi_server)
        assert [r.json()["desired_entry"] for r in requests] == [_plan_wire(S), None]
        assert _parse_entry_package_path(requests[1].path)[1] == cycle_id


# --- 6. Fill right before the cancel ----------------------------------------


def test_fill_on_the_expiry_bar_goes_to_position_management_not_cancel(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(
        engine_server, live_entry=_touch_engine({S}), open_trade=_open_trade_success()
    )
    open_position = _scripted(
        lambda _r: _open_position_closed(),
        lambda _r: _open_position_closed(),
        lambda _r: _open_position_closed(),
        lambda _r: _open_position_open(EXPIRY_BAR, "100"),
    )
    _set_abi_routes(abi_server, open_position=open_position, entry_package=_entry_package_applied)
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        _post_closed_bar(client, S)
        cycle_id = _cycle_id(app)
        for index in (1, 2, 3, 4):
            _post_closed_bar(client, _bar(index))

        state = _state(app)
        assert state.current_trade_cycle is not None
        assert state.current_trade_cycle.trade_cycle_id == cycle_id
        assert state.current_trade_cycle.frozen_entry_context is not None
        assert state.pending_entry_recovery is None
        # No CANCEL: the only entry-package request is the original APPLY.
        assert [r.json()["desired_entry"] for r in _entry_package_requests(abi_server)] == [
            _plan_wire(S)
        ]
        assert len([r for r in engine_server.requests if r.path == _OPEN_TRADE_PATH]) == 1


# --- 7. ema_anchor regression and structural checks --------------------------


def _run_two_bars(tmp_path: Path, engine_server, abi_server, config_text: str | None):
    _set_engine_routes(engine_server, live_entry=_touch_engine({S}))
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=_scripted(_entry_package_applied, _entry_package_absent),
    )
    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        config_text=config_text,
    )
    with TestClient(app) as client:
        _post_closed_bar(client, S)
        _post_closed_bar(client, _bar(1))
        return _state(app)


def _state_record_keys(tmp_path: Path) -> set[str]:
    lines = (tmp_path / "state" / "runtime_state.jsonl").read_text(encoding="utf-8").splitlines()
    keys: set[str] = set()
    for line in lines:
        record = json.loads(line)
        stack = [("", record)]
        while stack:
            prefix, value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    keys.add(f"{prefix}{key}")
                    stack.append((f"{prefix}{key}.", child))
    return keys


def test_ema_anchor_still_cancels_on_the_next_null_projection(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    state = _run_two_bars(tmp_path, engine_server, abi_server, config_text=None)

    assert state.current_trade_cycle is None
    assert [r.json()["desired_entry"] for r in _entry_package_requests(abi_server)] == [
        _plan_wire(S),
        None,
    ]


def test_touch_trigger_adds_no_state_fields_and_no_new_abi_request_kinds(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    anchor_dir = tmp_path / "ema_anchor"
    touch_dir = tmp_path / "touch_trigger"
    _run_two_bars(anchor_dir, engine_server, abi_server, config_text=None)
    anchor_requests = {(r.method, r.path.rsplit("/", 1)[-1]) for r in abi_server.requests}
    abi_server.requests.clear()

    state = _run_two_bars(
        touch_dir,
        engine_server,
        abi_server,
        config_text='live_entry_mode = "touch_trigger"\norder_lifetime_bars = 3\n',
    )
    touch_requests = {(r.method, r.path.rsplit("/", 1)[-1]) for r in abi_server.requests}

    assert state.current_trade_cycle is not None
    # Same ABI request kinds as ema_anchor; touch_trigger simply sent fewer.
    assert touch_requests <= anchor_requests
    # The held entry is persisted with the existing state shape only (the
    # ema_anchor run saved a cycle too, before cancelling it).
    assert _state_record_keys(touch_dir) <= _state_record_keys(anchor_dir)
