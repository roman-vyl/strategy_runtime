"""Runtime composition root: the single production construction path."""

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.config.loader import load_runtime_config
from strategy_runtime.config.startup import prepare_journal_path, prepare_specs_path
from strategy_runtime.infrastructure.abi import HttpxAbiOpenPositionLookupAdapter
from strategy_runtime.infrastructure.strategy_engine import (
    HttpxStrategyEngineLiveEntryAdapter,
    HttpxStrategyEngineOpenTradeAdapter,
)
from strategy_runtime.runtime.abi import HttpxAbiEntryPackageAdapter
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation_bridge import (
    AbiEntryPackageExecutionBridge,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.resolver import OpenPositionResolver
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.routing.router import StrategyUseCaseRouter
from strategy_runtime.runtime.state.identity import new_trade_cycle_id
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.shared.identifiers import new_identifier, utc_timestamp
from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentSpecification,
    FilesystemDeploymentCatalog,
)
from strategy_runtime.utility.deployment_selection import CommittedBarDeploymentSelector
from strategy_runtime.utility.handoff import StrategyCycleHandoffBoundary
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal


class _ClosableOutboundClient(Protocol):
    def close(self) -> None: ...


class _OutboundHttpClientLifecycle:
    """Single owner of the four outbound HTTP clients' `close()` lifecycle.

    One ordered collection, one idempotent close-all operation: the first
    `close_all_once()` call closes every added client at most once each; any
    later call is a no-op. One client's `close()` failure does not prevent
    closing the rest. Only two call sites are ever allowed to invoke
    `close_all_once()`: startup rollback (a partial-construction failure) and
    application shutdown (the FastAPI lifespan).
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._clients: list[_ClosableOutboundClient] = []
        self._closed = False

    def add[ClientT: _ClosableOutboundClient](self, client: ClientT) -> ClientT:
        self._clients.append(client)
        return client

    @property
    def clients(self) -> tuple[_ClosableOutboundClient, ...]:
        return tuple(self._clients)

    def close_all_once(self) -> None:
        if self._closed:
            return
        self._closed = True
        for client in self._clients:
            try:
                client.close()
            except Exception:
                self._logger.exception("Failed to close a production outbound HTTP client")


def build_application(
    environ: Mapping[str, str] | None = None,
    *,
    logger: logging.Logger | None = None,
) -> FastAPI:
    """Construct the single production application graph.

    A `ready=True` result always has the complete graph constructed: the
    utility contour, the shared state repository and keyed-mutex registry,
    all four outbound HTTP clients, and the semantic core wired as the
    production `StrategyCycleHandoffBoundary` sink. There is no parameter
    that returns a partial or utility-only ready result.

    Every step from the first outbound HTTP client constructed through
    returning the ready FastAPI application -- including the semantic graph,
    the thin dispatch sink, the utility graph, lifespan construction,
    `create_http_app(...)`, and `app.state` attachment -- is inside one
    construction boundary. Any failure anywhere in that boundary triggers
    `lifecycle.close_all_once()` (startup rollback) before a not-ready
    application is returned; no partially assembled `ready=True` application
    is ever left behind.
    """
    runtime_logger = logger or logging.getLogger("strategy_runtime")
    lifecycle = _OutboundHttpClientLifecycle(runtime_logger)
    try:
        config = load_runtime_config(environ)
        prepare_journal_path(config.journal_path)
        prepare_specs_path(config.specs_path)

        catalog = FilesystemDeploymentCatalog(config.specs_path)
        selector = CommittedBarDeploymentSelector()
        journal = JsonlProcessingJournal(
            config.journal_path,
            event_id_factory=new_identifier,
            timestamp_factory=utc_timestamp,
            logger=runtime_logger,
        )

        live_entry_client = lifecycle.add(
            HttpxStrategyEngineLiveEntryAdapter(
                base_url=config.strategy_engine_base_url,
                timeout_seconds=config.strategy_engine_timeout_seconds,
            )
        )
        open_trade_client = lifecycle.add(
            HttpxStrategyEngineOpenTradeAdapter(
                base_url=config.strategy_engine_base_url,
                timeout_seconds=config.strategy_engine_timeout_seconds,
            )
        )
        open_position_client = lifecycle.add(
            HttpxAbiOpenPositionLookupAdapter(
                base_url=config.abi_base_url,
                timeout_seconds=config.abi_open_position_timeout_seconds,
            )
        )
        entry_package_client = lifecycle.add(
            HttpxAbiEntryPackageAdapter(
                base_url=config.abi_base_url,
                timeout_seconds=config.abi_entry_package_timeout_seconds,
            )
        )

        open_position_resolver = OpenPositionResolver(open_position_client)
        use_case_router = StrategyUseCaseRouter(
            live_entry_engine=live_entry_client,
            open_trade_engine=open_trade_client,
        )
        entry_execution_bridge = AbiEntryPackageExecutionBridge(entry_package_client)
        state_repository = InMemoryStrategyInstanceRuntimeStateRepository()
        keyed_mutex_registry = StrategyInstanceKeyedMutexRegistry()
        entry_reconciliation_orchestrator = EntryReconciliationOrchestrator(
            new_trade_cycle_id,
            entry_execution_bridge,
        )
        strategy_runtime_orchestrator = StrategyRuntimeOrchestrator(
            state_repository=state_repository,
            open_position_resolver=open_position_resolver,
            use_case_router=use_case_router,
            keyed_mutex_registry=keyed_mutex_registry,
            entry_reconciliation_orchestrator=entry_reconciliation_orchestrator,
        )

        def process_strategy_cycle(
            unit: StrategyBarProcessingUnit[DeploymentSpecification],
        ) -> None:
            strategy_runtime_orchestrator.process(unit)

        handoff_boundary = StrategyCycleHandoffBoundary(process_strategy_cycle)
        orchestrator = CommittedBarOrchestrator(
            deployment_catalog=catalog,
            deployment_selector=selector,
            strategy_cycle_dispatcher=handoff_boundary,
            processing_journal=journal,
        )

        def process_committed_bar(event: CommittedBarEvent) -> None:
            orchestrator.process(event)

        @asynccontextmanager
        async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
            try:
                yield
            finally:
                lifecycle.close_all_once()

        app = create_http_app(
            ready=True,
            trace_id_factory=new_identifier,
            process_committed_bar=process_committed_bar,
            logger=runtime_logger,
            lifespan=_lifespan,
        )
        app.state.state_repository = state_repository
        app.state.keyed_mutex_registry = keyed_mutex_registry
        app.state.outbound_http_client_lifecycle = lifecycle
        app.state.outbound_http_clients = lifecycle.clients

    except Exception:
        runtime_logger.exception("Runtime startup readiness failed")
        lifecycle.close_all_once()
        return create_http_app(
            ready=False,
            trace_id_factory=new_identifier,
            process_committed_bar=None,
            logger=runtime_logger,
        )

    return app
