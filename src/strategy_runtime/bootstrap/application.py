"""Runtime composition root for the completed utility orchestration contour."""

import logging
from collections.abc import Mapping

from fastapi import FastAPI

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.config.loader import load_runtime_config
from strategy_runtime.config.startup import prepare_journal_path, prepare_specs_path
from strategy_runtime.shared.identifiers import new_identifier, utc_timestamp
from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentSpecification,
    FilesystemDeploymentCatalog,
)
from strategy_runtime.utility.deployment_selection import CommittedBarDeploymentSelector
from strategy_runtime.utility.handoff import (
    StrategyCycleHandoffBoundary,
    StrategyCycleHandoffSink,
)
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal


def build_application(
    environ: Mapping[str, str] | None = None,
    *,
    logger: logging.Logger | None = None,
    strategy_cycle_handoff: StrategyCycleHandoffSink[DeploymentSpecification] | None = None,
) -> FastAPI:
    runtime_logger = logger or logging.getLogger("strategy_runtime")
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
        handoff_boundary = StrategyCycleHandoffBoundary(strategy_cycle_handoff)
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
        return create_http_app(
            ready=False,
            trace_id_factory=new_identifier,
            process_committed_bar=None,
            logger=runtime_logger,
        )

    return create_http_app(
        ready=True,
        trace_id_factory=new_identifier,
        process_committed_bar=process_committed_bar,
        logger=runtime_logger,
    )
