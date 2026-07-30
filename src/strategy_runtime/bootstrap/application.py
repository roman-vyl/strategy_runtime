"""Runtime composition root: the single production construction path."""

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
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


def _close_outbound_clients(
    clients: Sequence[_ClosableOutboundClient], logger: logging.Logger
) -> None:
    """Close every owned outbound HTTP client exactly once, independently."""
    for client in clients:
        try:
            client.close()
        except Exception:
            logger.exception("Failed to close a production outbound HTTP client")


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
    """
    runtime_logger = logger or logging.getLogger("strategy_runtime")
    constructed_clients: list[_ClosableOutboundClient] = []
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

        live_entry_client = HttpxStrategyEngineLiveEntryAdapter(
            base_url=config.strategy_engine_base_url,
            timeout_seconds=config.strategy_engine_timeout_seconds,
        )
        constructed_clients.append(live_entry_client)
        open_trade_client = HttpxStrategyEngineOpenTradeAdapter(
            base_url=config.strategy_engine_base_url,
            timeout_seconds=config.strategy_engine_timeout_seconds,
        )
        constructed_clients.append(open_trade_client)
        open_position_client = HttpxAbiOpenPositionLookupAdapter(
            base_url=config.abi_base_url,
            timeout_seconds=config.abi_open_position_timeout_seconds,
        )
        constructed_clients.append(open_position_client)
        entry_package_client = HttpxAbiEntryPackageAdapter(
            base_url=config.abi_base_url,
            timeout_seconds=config.abi_entry_package_timeout_seconds,
        )
        constructed_clients.append(entry_package_client)

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

    except Exception:
        runtime_logger.exception("Runtime startup readiness failed")
        _close_outbound_clients(constructed_clients, runtime_logger)
        return create_http_app(
            ready=False,
            trace_id_factory=new_identifier,
            process_committed_bar=None,
            logger=runtime_logger,
        )

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            _close_outbound_clients(constructed_clients, runtime_logger)

    app = create_http_app(
        ready=True,
        trace_id_factory=new_identifier,
        process_committed_bar=process_committed_bar,
        logger=runtime_logger,
        lifespan=_lifespan,
    )
    app.state.state_repository = state_repository
    app.state.keyed_mutex_registry = keyed_mutex_registry
    app.state.outbound_http_clients = tuple(constructed_clients)

    return app
