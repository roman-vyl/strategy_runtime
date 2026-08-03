"""Vertical live-entry E2E and per-boundary failure tests for I4d.

These tests drive the complete production composition (`build_application`
with full Engine/ABI configuration) through a real, lifespan-aware
`TestClient` webhook request and real local HTTP servers standing in for
Strategy Engine and ABI. Downstream outcomes are verified through repository
state, recorded fake-server calls, and processing-journal records -- never
through HTTP status or body, which stays the already-sent `200 accepted`
regardless of background outcome (design.md secs. 4 and 9).

Each `app` is driven through `with TestClient(app) as client:` so the FastAPI
lifespan actually starts and stops (outbound HTTP clients are constructed on
`build_application` and closed on lifespan shutdown, exercised here rather
than left dormant).
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.runtime.abi.entry_package_errors import (
    AbiEntryPackageNetworkFailure,
    AbiEntryPackageProtocolError,
    AbiEntryPackageTimeout,
)
from strategy_runtime.runtime.entry_reconciliation_bridge import (
    AbiEntryPackageExecutionBridge,
    EntryReconciliationExecutionError,
)
from strategy_runtime.utility.deployment_catalog import derive_strategy_instance_id

from ._fake_http_server import (
    DisconnectResponse,
    FakeHttpServer,
    FakeResponse,
    RecordedRequest,
    path_prefix_route,
    route,
    sequential,
)

_STRATEGY_ID = "ema_pullback"
_TICKER = "BTCUSDT.P"
_TIMEFRAME = "5m"
_RAW_SPEC = {"direction": {"fast_ema": 20, "anchor_ema": 200}}
_STRATEGY_INSTANCE_ID = derive_strategy_instance_id(
    strategy_id=_STRATEGY_ID, ticker=_TICKER, base_timeframe=_TIMEFRAME, raw_spec=_RAW_SPEC
)
_LIVE_ENTRY_PATH = "/v1/strategy-evaluations/live-entry"
_OPEN_TRADE_PATH = "/v1/strategy-evaluations/open-trade"
_ENTRY_PACKAGE_PATH_RE = re.compile(
    r"^/v1/strategy-instances/([^/]+)/trade-cycles/([^/]+)/entry-package$"
)
_UNREACHABLE_URL = "http://127.0.0.1:1"


def _write_deployment(specs_path: Path) -> None:
    specs_path.mkdir(parents=True, exist_ok=True)
    (specs_path / "deployment.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "ticker": _TICKER,
                "base_timeframe": _TIMEFRAME,
                "strategy_id": _STRATEGY_ID,
                "raw_spec": _RAW_SPEC,
            }
        ),
        encoding="utf-8",
    )


def _build_app(
    tmp_path: Path,
    *,
    engine_base_url: str,
    abi_base_url: str,
    engine_timeout: float = 5.0,
    abi_open_position_timeout: float = 5.0,
    abi_entry_package_timeout: float = 5.0,
):
    _write_deployment(tmp_path / "specs")
    env = {
        "RUNTIME_SPECS_PATH": str(tmp_path / "specs"),
        "RUNTIME_JOURNAL_PATH": str(tmp_path / "journal" / "runtime.jsonl"),
        "RUNTIME_STRATEGY_ENGINE_BASE_URL": engine_base_url,
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS": str(engine_timeout),
        "RUNTIME_ABI_BASE_URL": abi_base_url,
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS": str(abi_open_position_timeout),
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS": str(abi_entry_package_timeout),
    }
    return build_application(env)


def _post_closed_bar(client: TestClient, open_time_ms: int) -> object:
    return client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": _TICKER, "timeframe": _TIMEFRAME, "open_time_ms": open_time_ms},
    )


def _read_journal(journal_path: Path) -> list[dict[str, object]]:
    if not journal_path.exists():
        return []
    return [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]


def _dispatch_outcomes(journal_path: Path) -> list[dict[str, object]]:
    return [
        record
        for record in _read_journal(journal_path)
        if record["event_type"]
        in {"strategy_cycle_dispatch_succeeded", "strategy_cycle_dispatch_failed"}
    ]


# --- wire-shape builders -----------------------------------------------------


def _open_position_closed() -> FakeResponse:
    return FakeResponse(
        200, {"position_open": False, "first_fill_at_ms": None, "average_entry_price": None}
    )


def _open_position_open(first_fill_at_ms: int, average_entry_price: str) -> FakeResponse:
    return FakeResponse(
        200,
        {
            "position_open": True,
            "first_fill_at_ms": first_fill_at_ms,
            "average_entry_price": average_entry_price,
        },
    )


def _abi_open_position_public_error() -> FakeResponse:
    return FakeResponse(
        422,
        {
            "error": {
                "code": "validation_failed",
                "message": "malformed identifier",
                "details": [{"path": "/path/trade_cycle_id", "message": "malformed"}],
            }
        },
    )


def _abi_open_position_protocol_error() -> FakeResponse:
    return FakeResponse(200, {"unexpected": "shape"})


def _desired_entry_wire() -> dict[str, object]:
    return {
        "side": "long",
        "source_plan_bar_open_time_ms": 1720000000000,
        "planned_entry_price": "100",
        "initial_stop_price": "90",
        "initial_take_price": "120",
        "locked_exit_profile": "standard",
    }


def _live_entry_present() -> FakeResponse:
    return FakeResponse(200, {"desired_entry": _desired_entry_wire()})


def _live_entry_absent() -> FakeResponse:
    return FakeResponse(200, {"desired_entry": None})


def _engine_public_error() -> FakeResponse:
    return FakeResponse(
        422,
        {
            "error": "validation_failed",
            "message": "bad raw_spec",
            "details": {},
            "request_id": "req-1",
        },
    )


def _engine_protocol_error() -> FakeResponse:
    return FakeResponse(200, {"unexpected": "shape"})


def _open_trade_success() -> FakeResponse:
    return FakeResponse(
        200,
        {
            "desired_protection": {"stop_price": "90", "take_price": "120"},
            "close_signal": {"active": False, "reason": None, "component_id": None, "layer": None},
            "diagnostics": {},
        },
    )


def _parse_entry_package_path(path: str) -> tuple[str, str]:
    match = _ENTRY_PACKAGE_PATH_RE.match(path)
    assert match is not None, f"unexpected entry-package path: {path}"
    return unquote(match.group(1)), unquote(match.group(2))


def _entry_package_applied(request: RecordedRequest) -> FakeResponse:
    sid, cid = _parse_entry_package_path(request.path)
    body = request.json()
    return FakeResponse(
        200,
        {
            "strategy_instance_id": sid,
            "trade_cycle_id": cid,
            "status": "entry_package_applied",
            "applied_desired_entry": body["desired_entry"],
            "calculated_quantity": "1.5",
        },
    )


def _entry_package_absent(request: RecordedRequest) -> FakeResponse:
    sid, cid = _parse_entry_package_path(request.path)
    return FakeResponse(
        200, {"strategy_instance_id": sid, "trade_cycle_id": cid, "status": "entry_package_absent"}
    )


def _entry_package_public_error() -> FakeResponse:
    return FakeResponse(
        422,
        {
            "error": {
                "code": "validation_failed",
                "message": "bad entry package",
                "details": [{"path": "risk_multiplier", "message": "invalid"}],
            }
        },
    )


def _entry_package_protocol_error() -> FakeResponse:
    return FakeResponse(200, {"unexpected": "shape"})


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


def _set_engine_routes(
    server: FakeHttpServer,
    *,
    live_entry: object = None,
    open_trade: object = None,
) -> None:
    routes: dict[str, object] = {}
    if live_entry is not None:
        routes[_LIVE_ENTRY_PATH] = live_entry
    if open_trade is not None:
        routes[_OPEN_TRADE_PATH] = open_trade
    server._handler = route(routes, not_found=FakeResponse(404, {"error": "not_found"}))


def _set_abi_routes(
    server: FakeHttpServer,
    *,
    open_position: object = None,
    entry_package: object = None,
) -> None:
    routes: dict[str, object] = {}
    if open_position is not None:
        routes["/open-position"] = open_position
    if entry_package is not None:
        routes["/entry-package"] = entry_package
    server._handler = path_prefix_route(routes, not_found=FakeResponse(404, {"error": "not_found"}))


# --- happy path / NO_OP / CANCEL / open-trade-unsupported --------------------


def test_happy_path_applies_desired_entry_and_saves_current_trade_cycle(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_live_entry_present())
    _set_abi_routes(
        abi_server, open_position=_open_position_closed(), entry_package=_entry_package_applied
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        response = _post_closed_bar(client, 1)

        assert response.status_code == 200
        assert response.json() == {"status": "accepted"}

        state = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state is not None
        assert state.current_trade_cycle is not None
        assert state.current_trade_cycle.applied_entry_package.calculated_quantity == "1.5"

        # Cycle 1 has no prior current_trade_cycle, so the resolver never
        # calls ABI's pair-addressed open-position endpoint -- there is no
        # trade_cycle_id yet to place in the request.
        open_position_requests = [r for r in abi_server.requests if "/open-position" in r.path]
        assert len(open_position_requests) == 0

        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 1
        assert entry_package_requests[0].json()["risk_multiplier"] == state.risk_multiplier == "1"


def test_brand_new_instance_reaches_live_entry_without_any_abi_open_position_call(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    """current_trade_cycle=None -> the resolver never calls ABI at all.

    There is nothing to configure a fake open-position response for: no
    trade_cycle_id exists yet, so no request is ever sent.
    """
    _set_engine_routes(engine_server, live_entry=_live_entry_absent())
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        response = _post_closed_bar(client, 1)

        assert response.status_code == 200
        assert abi_server.requests == []
        live_entry_requests = [r for r in engine_server.requests if r.path == _LIVE_ENTRY_PATH]
        assert len(live_entry_requests) == 1

        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_succeeded"


def test_existing_trade_cycle_reaches_live_entry_after_real_abi_closed_response(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    """Once a current_trade_cycle exists, ABI is actually asked -- and a
    real (not skipped) closed response still routes to live-entry."""
    _set_engine_routes(
        engine_server, live_entry=sequential(_live_entry_present(), _live_entry_absent())
    )
    _set_abi_routes(
        abi_server, open_position=_open_position_closed(), entry_package=_entry_package_applied
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        first = _post_closed_bar(client, 1)
        assert first.status_code == 200
        state = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state is not None
        assert state.current_trade_cycle is not None
        trade_cycle_id = state.current_trade_cycle.trade_cycle_id

        second = _post_closed_bar(client, 2)
        assert second.status_code == 200

        open_position_requests = [r for r in abi_server.requests if "/open-position" in r.path]
        assert len(open_position_requests) == 1
        assert unquote(open_position_requests[0].path) == (
            f"/v1/strategy-instances/{_STRATEGY_INSTANCE_ID}"
            f"/trade-cycles/{trade_cycle_id}/open-position"
        )

        live_entry_requests = [r for r in engine_server.requests if r.path == _LIVE_ENTRY_PATH]
        assert len(live_entry_requests) == 2


def test_no_op_when_desired_entry_is_null_and_no_current_cycle(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(engine_server, live_entry=_live_entry_absent())
    _set_abi_routes(abi_server, open_position=_open_position_closed())

    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        response = _post_closed_bar(client, 1)

        assert response.status_code == 200
        open_position_requests = [r for r in abi_server.requests if "/open-position" in r.path]
        assert len(open_position_requests) == 0
        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 0

        state = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state is not None
        assert state.current_trade_cycle is None


def test_cancel_clears_cycle_only_after_entry_package_absent_confirmation(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    _set_engine_routes(
        engine_server, live_entry=sequential(_live_entry_present(), _live_entry_absent())
    )
    _set_abi_routes(
        abi_server,
        open_position=_open_position_closed(),
        entry_package=sequential(_entry_package_applied, _entry_package_absent),
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        first = _post_closed_bar(client, 1)
        assert first.status_code == 200
        state_after_apply = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_apply is not None
        assert state_after_apply.current_trade_cycle is not None

        second = _post_closed_bar(client, 2)
        assert second.status_code == 200
        state_after_cancel = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_cancel is not None
        assert state_after_cancel.current_trade_cycle is None

        # Cycle 1 had no current_trade_cycle (no ABI open-position call);
        # cycle 2 had one, so the resolver called ABI exactly once.
        open_position_requests = [r for r in abi_server.requests if "/open-position" in r.path]
        assert len(open_position_requests) == 1

        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 2


def test_legacy_pre_alignment_open_position_success_shape_is_no_longer_accepted(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    """The pre-alignment success shape (entry_bar_open_time_ms/
    executed_entry_price) is a protocol error now, not a silently coerced
    result. This can only be observed once ABI is actually called, so cycle
    1 establishes a current_trade_cycle first."""
    _set_engine_routes(engine_server, live_entry=_live_entry_present())
    _set_abi_routes(
        abi_server, open_position=_open_position_closed(), entry_package=_entry_package_applied
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        first = _post_closed_bar(client, 1)
        assert first.status_code == 200
        state_after_apply = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_apply is not None
        assert state_after_apply.current_trade_cycle is not None

        legacy_shape = FakeResponse(
            200,
            {
                "position_open": False,
                "entry_bar_open_time_ms": None,
                "executed_entry_price": None,
            },
        )
        _set_abi_routes(
            abi_server, open_position=legacy_shape, entry_package=_entry_package_applied
        )

        second = _post_closed_bar(client, 2)
        assert second.status_code == 200

        state_after_failure = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_failure == state_after_apply

        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 1

        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_failed"


def test_open_trade_projection_remains_explicitly_unsupported(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer
) -> None:
    """position_open=true fails closed in the router itself, before any
    Engine open-trade call -- see design.md "position_open=true fails
    closed before Engine, with no field mapping". The fake Engine open-trade
    route is still configured so a regression that starts calling it again
    would be caught (request count would become nonzero)."""
    _set_engine_routes(
        engine_server, live_entry=_live_entry_present(), open_trade=_open_trade_success()
    )
    _set_abi_routes(
        abi_server,
        open_position=_open_position_open(1720000000000, "100"),
        entry_package=_entry_package_applied,
    )
    app = _build_app(
        tmp_path, engine_base_url=engine_server.base_url, abi_base_url=abi_server.base_url
    )

    with TestClient(app) as client:
        first = _post_closed_bar(client, 1)
        assert first.status_code == 200
        state_after_apply = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_apply is not None
        assert state_after_apply.current_trade_cycle is not None

        second = _post_closed_bar(client, 2)
        assert second.status_code == 200

        state_after_open_trade = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_open_trade == state_after_apply

        # Cycle 1: no current_trade_cycle, no ABI open-position call. Cycle
        # 2: current_trade_cycle exists, exactly one ABI open-position call,
        # answered "open" -- and the router fails closed on that answer
        # without ever reaching Strategy Engine's open-trade port.
        open_position_requests = [r for r in abi_server.requests if "/open-position" in r.path]
        assert len(open_position_requests) == 1

        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 1

        open_trade_requests = [r for r in engine_server.requests if r.path == _OPEN_TRADE_PATH]
        assert open_trade_requests == []

        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_failed"
        assert outcomes[-1]["strategy_instance_id"] == _STRATEGY_INSTANCE_ID


# --- per-boundary failures ----------------------------------------------------

_FAILURE_KINDS = ["timeout", "network_failure", "protocol_error", "public_error"]


@pytest.mark.parametrize("kind", _FAILURE_KINDS)
def test_abi_open_position_lookup_failure_stops_before_engine(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer, kind: str
) -> None:
    """The resolver only calls ABI's open-position endpoint once a
    current_trade_cycle exists, so this test first establishes one (cycle 1,
    no ABI open-position call at all) before injecting the failure on cycle
    2's lookup. `network_failure` uses a per-route `DisconnectResponse` on
    the same real server/base URL, not an unreachable URL, since cycle 1's
    entry-package call must still succeed against that same base URL."""
    _set_engine_routes(engine_server, live_entry=_live_entry_present())
    abi_open_position_timeout = 0.05 if kind == "timeout" else 5.0

    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        abi_open_position_timeout=abi_open_position_timeout,
    )

    with TestClient(app) as client:
        _set_abi_routes(abi_server, entry_package=_entry_package_applied)
        first = _post_closed_bar(client, 1)
        assert first.status_code == 200
        state_after_apply = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_apply is not None
        assert state_after_apply.current_trade_cycle is not None
        live_entry_requests_before = len(
            [r for r in engine_server.requests if r.path == _LIVE_ENTRY_PATH]
        )

        if kind == "timeout":
            open_position_response: object = FakeResponse(200, {}, delay_seconds=1.0)
        elif kind == "network_failure":
            open_position_response = DisconnectResponse()
        elif kind == "protocol_error":
            open_position_response = _abi_open_position_protocol_error()
        else:
            open_position_response = _abi_open_position_public_error()
        _set_abi_routes(
            abi_server, open_position=open_position_response, entry_package=_entry_package_applied
        )

        second = _post_closed_bar(client, 2)
        assert second.status_code == 200

        live_entry_requests_after = len(
            [r for r in engine_server.requests if r.path == _LIVE_ENTRY_PATH]
        )
        assert live_entry_requests_after == live_entry_requests_before

        state_after_failure = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state_after_failure == state_after_apply

        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_failed"


@pytest.mark.parametrize("kind", _FAILURE_KINDS)
def test_strategy_engine_projection_failure_stops_before_abi_entry_package(
    tmp_path: Path, engine_server: FakeHttpServer, abi_server: FakeHttpServer, kind: str
) -> None:
    _set_abi_routes(abi_server, open_position=_open_position_closed())
    engine_base_url = engine_server.base_url
    engine_timeout = 5.0

    if kind == "timeout":
        _set_engine_routes(engine_server, live_entry=FakeResponse(200, {}, delay_seconds=1.0))
        engine_timeout = 0.05
    elif kind == "network_failure":
        engine_base_url = _UNREACHABLE_URL
    elif kind == "protocol_error":
        _set_engine_routes(engine_server, live_entry=_engine_protocol_error())
    else:
        _set_engine_routes(engine_server, live_entry=_engine_public_error())

    app = _build_app(
        tmp_path,
        engine_base_url=engine_base_url,
        abi_base_url=abi_server.base_url,
        engine_timeout=engine_timeout,
    )

    with TestClient(app) as client:
        response = _post_closed_bar(client, 1)

        assert response.status_code == 200
        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 0

        state = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state is None or state.current_trade_cycle is None

        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_failed"


_ENTRY_PACKAGE_EXPECTED_CAUSE: dict[str, type[Exception] | None] = {
    "timeout": AbiEntryPackageTimeout,
    "network_failure": AbiEntryPackageNetworkFailure,
    "protocol_error": AbiEntryPackageProtocolError,
    "public_error": None,
}


@pytest.mark.parametrize("kind", _FAILURE_KINDS)
def test_abi_entry_package_failure_leaves_no_saved_cycle(
    tmp_path: Path,
    engine_server: FakeHttpServer,
    abi_server: FakeHttpServer,
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every one of the four ABI entry-package failure kinds is exercised
    end to end, including `network_failure`: the fake ABI server accepts the
    TCP connection and records the request, then disconnects before writing
    any HTTP response (`DisconnectResponse`), which httpx surfaces as
    `httpx.RemoteProtocolError` (a `TransportError` subclass) -- the same
    transport-failure family the existing `HttpxAbiEntryPackageAdapter`
    already maps to `AbiEntryPackageNetworkFailure`. ABI open-position and
    entry-package share one `RUNTIME_ABI_BASE_URL`, but the fake server
    dispatches per-path, so open-position keeps succeeding normally on the
    very same server/base URL while only the entry-package route fails."""
    captured_errors: list[EntryReconciliationExecutionError] = []
    real_execute = AbiEntryPackageExecutionBridge.execute

    def _recording_execute(self: object, command: object, source_state: object) -> object:
        try:
            return real_execute(self, command, source_state)  # type: ignore[arg-type]
        except EntryReconciliationExecutionError as exc:
            captured_errors.append(exc)
            raise

    monkeypatch.setattr(AbiEntryPackageExecutionBridge, "execute", _recording_execute)

    _set_engine_routes(engine_server, live_entry=_live_entry_present())
    entry_package_timeout = 5.0

    if kind == "timeout":
        _set_abi_routes(
            abi_server,
            open_position=_open_position_closed(),
            entry_package=FakeResponse(200, {}, delay_seconds=1.0),
        )
        entry_package_timeout = 0.05
    elif kind == "network_failure":
        _set_abi_routes(
            abi_server,
            open_position=_open_position_closed(),
            entry_package=DisconnectResponse(),
        )
    elif kind == "protocol_error":
        _set_abi_routes(
            abi_server,
            open_position=_open_position_closed(),
            entry_package=_entry_package_protocol_error(),
        )
    else:
        _set_abi_routes(
            abi_server,
            open_position=_open_position_closed(),
            entry_package=_entry_package_public_error(),
        )

    app = _build_app(
        tmp_path,
        engine_base_url=engine_server.base_url,
        abi_base_url=abi_server.base_url,
        abi_entry_package_timeout=entry_package_timeout,
    )

    with TestClient(app) as client:
        response = _post_closed_bar(client, 1)

        # HTTP acknowledgement is unaffected by the downstream outcome.
        assert response.status_code == 200
        assert response.json() == {"status": "accepted"}

        # Cycle 1 has no prior current_trade_cycle, so the resolver never
        # calls ABI's pair-addressed open-position endpoint for this cycle.
        open_position_requests = [r for r in abi_server.requests if "/open-position" in r.path]
        assert len(open_position_requests) == 0
        live_entry_requests = [r for r in engine_server.requests if r.path == _LIVE_ENTRY_PATH]
        assert len(live_entry_requests) == 1

        # The entry-package endpoint was attempted exactly once, with no
        # automatic retry, regardless of how it failed.
        entry_package_requests = [r for r in abi_server.requests if "/entry-package" in r.path]
        assert len(entry_package_requests) == 1

        # The bridge classified the underlying failure and
        # EntryReconciliationExecutionError propagated out of the semantic
        # core uncaught.
        assert len(captured_errors) == 1
        error = captured_errors[0]
        expected_cause = _ENTRY_PACKAGE_EXPECTED_CAUSE[kind]
        if expected_cause is None:
            assert error.__cause__ is None
            assert error.public_error is not None
        else:
            assert isinstance(error.__cause__, expected_cause)

        # CommittedBarOrchestrator caught the propagated failure and
        # journaled it; no repository save occurred.
        state = app.state.state_repository.get(_STRATEGY_INSTANCE_ID)
        assert state is None or state.current_trade_cycle is None

        outcomes = _dispatch_outcomes(tmp_path / "journal" / "runtime.jsonl")
        assert outcomes[-1]["event_type"] == "strategy_cycle_dispatch_failed"
        assert outcomes[-1]["strategy_instance_id"] == _STRATEGY_INSTANCE_ID
