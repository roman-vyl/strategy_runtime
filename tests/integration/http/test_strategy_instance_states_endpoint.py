"""HTTP integration tests for GET /v1/strategy-instance-states."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.errors import StrategyInstanceStateError
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingCloseRecovery,
    PendingEntryRecovery,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.runtime.trading_state import StrategyTradingStateService
from strategy_runtime.utility.deployment_catalog import (
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

PATH = "/v1/strategy-instance-states"
TICKERS = ("BTCUSDT.P", "ETHUSDT.P", "SOLUSDT.P")
RAW_SPEC = {"anchor": 500}


def sid(ticker: str) -> str:
    return derive_strategy_instance_id(
        strategy_id="ema_pullback", ticker=ticker, base_timeframe="5m", raw_spec=RAW_SPEC
    )


class QuietLogger:
    def info(self, message: str, *args: object, **kwargs: object) -> None: ...

    def exception(self, message: str, *args: object, **kwargs: object) -> None: ...

    def error(self, message: str, **kwargs: object) -> None: ...

    def warning(self, message: str, **kwargs: object) -> None: ...


class Env:
    def __init__(self, tmp_path: Path) -> None:
        for ticker in TICKERS:
            (tmp_path / f"{ticker}.json").write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "ticker": ticker,
                        "base_timeframe": "5m",
                        "strategy_id": "ema_pullback",
                        "raw_spec": RAW_SPEC,
                    }
                ),
                encoding="utf-8",
            )
        self.catalog = FilesystemDeploymentCatalog(tmp_path)
        self.repository = InMemoryStrategyInstanceRuntimeStateRepository()

    def state(self, ticker: str, **changes: object) -> None:
        state = self.repository.get_or_create(
            GetOrCreateStrategyInstanceRuntimeStateRequest(
                strategy_instance_id=sid(ticker),
                strategy_id="ema_pullback",
                instrument=ticker,
                base_timeframe="5m",
                raw_spec=RAW_SPEC,
                source_path=f"{ticker}.json",
            )
        )
        self.repository.save(replace(state, **changes))

    def client(
        self, *, ready: bool = True, repository: object | None = None, load: object | None = None
    ) -> TestClient:
        service = StrategyTradingStateService(
            load_snapshot=load or self.catalog.load_snapshot,  # type: ignore[arg-type]
            state_repository=repository or self.repository,  # type: ignore[arg-type]
        )
        app = create_http_app(
            ready=ready,
            committed_bar_intake=None,
            process_first_fill=None,
            list_trading_states=service.list,
            logger=QuietLogger(),  # type: ignore[arg-type]
        )
        return TestClient(app)


def entry(side: str = "long") -> DesiredEntry:
    return DesiredEntry(side, 900, "100", "99", "103", "runner")  # type: ignore[arg-type]


def cycle(cycle_id: str, *, filled: bool = False, side: str = "long") -> CurrentTradeCycle:
    return CurrentTradeCycle(
        trade_cycle_id=cycle_id,
        applied_entry_package=AppliedEntryPackage(entry(side), "0.01"),
        frozen_entry_context=(
            FrozenExecutedEntryContext(entry(side), 1_000, 900) if filled else None
        ),
    )


def by_ticker(body: dict[str, object]) -> dict[str, dict[str, object]]:
    items = body["strategy_instances"]
    assert isinstance(items, list)
    return {item["strategy_instance_id"]: item for item in items}


def test_flat_pending_and_in_position_are_reported(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state("BTCUSDT.P")
    env.state("ETHUSDT.P", current_trade_cycle=cycle("c-eth"))
    env.state("SOLUSDT.P", current_trade_cycle=cycle("c-sol", filled=True, side="short"))

    response = env.client().get(PATH)

    assert response.status_code == 200
    items = by_ticker(response.json())
    assert items[sid("BTCUSDT.P")] == {
        "strategy_instance_id": sid("BTCUSDT.P"),
        "trade_state": "flat",
        "trade_cycle_id": None,
        "side": None,
        "first_fill_at_ms": None,
        "recovery_pending": None,
    }
    assert items[sid("ETHUSDT.P")] == {
        "strategy_instance_id": sid("ETHUSDT.P"),
        "trade_state": "entry_pending",
        "trade_cycle_id": "c-eth",
        "side": "long",
        "first_fill_at_ms": None,
        "recovery_pending": None,
    }
    assert items[sid("SOLUSDT.P")] == {
        "strategy_instance_id": sid("SOLUSDT.P"),
        "trade_state": "in_position",
        "trade_cycle_id": "c-sol",
        "side": "short",
        "first_fill_at_ms": 1_000,
        "recovery_pending": None,
    }


def test_never_processed_instance_is_flat_and_order_is_the_catalog_order(tmp_path: Path) -> None:
    env = Env(tmp_path)

    body = env.client().get(PATH).json()

    expected = [d.strategy_instance_id for d in env.catalog.load_snapshot().accepted_deployments]
    assert [item["strategy_instance_id"] for item in body["strategy_instances"]] == expected
    assert {item["trade_state"] for item in body["strategy_instances"]} == {"flat"}
    assert len(expected) == 3


def test_recovery_markers_are_reported_independently_of_the_trade_state(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state("BTCUSDT.P", pending_entry_recovery=PendingEntryRecovery("c-btc"))
    env.state(
        "ETHUSDT.P",
        current_trade_cycle=cycle("c-eth", filled=True),
        pending_close_recovery=PendingCloseRecovery("c-eth"),
    )

    items = by_ticker(env.client().get(PATH).json())

    assert items[sid("BTCUSDT.P")]["trade_state"] == "flat"
    assert items[sid("BTCUSDT.P")]["recovery_pending"] == "entry"
    assert items[sid("ETHUSDT.P")]["trade_state"] == "in_position"
    assert items[sid("ETHUSDT.P")]["recovery_pending"] == "close"


def test_the_route_writes_nothing(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state("BTCUSDT.P", current_trade_cycle=cycle("c-btc"))
    before = {t: env.repository.get(sid(t)) for t in TICKERS}

    env.client().get(PATH)

    assert {t: env.repository.get(sid(t)) for t in TICKERS} == before


def test_not_ready_before_startup(tmp_path: Path) -> None:
    response = Env(tmp_path).client(ready=False).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_catalog_unavailable(tmp_path: Path) -> None:
    from strategy_runtime.utility.deployment_catalog import DeploymentCatalogUnavailableError

    def load() -> object:
        raise DeploymentCatalogUnavailableError("down")

    response = Env(tmp_path).client(load=load).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "catalog_unavailable"}


def test_state_unreadable_returns_no_partial_list(tmp_path: Path) -> None:
    env = Env(tmp_path)
    inner = env.repository

    class Broken:
        calls = 0

        def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
            self.calls += 1
            if self.calls == 2:
                raise StrategyInstanceStateError("unreadable")
            return inner.get(strategy_instance_id)

    response = env.client(repository=Broken()).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "state_unavailable"}


def test_unexpected_failure_is_internal_error(tmp_path: Path) -> None:
    class Boom:
        def get(self, strategy_instance_id: str) -> None:
            raise RuntimeError("boom")

    response = Env(tmp_path).client(repository=Boom()).get(PATH)

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


def test_other_methods_are_not_allowed(tmp_path: Path) -> None:
    client = Env(tmp_path).client()
    sender: dict[str, Callable[..., object]] = {
        "POST": client.post,
        "PUT": client.put,
        "PATCH": client.patch,
        "DELETE": client.delete,
    }
    for method, send in sender.items():
        response = send(PATH)
        assert response.status_code == 405, method  # type: ignore[attr-defined]
