"""FastAPI application adapter."""

import logging
import queue
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import Lifespan

from strategy_runtime.adapters.http.models import (
    AcceptedResponse,
    CatalogUnavailableResponse,
    ChartLayersRefusedResponse,
    ChartLayersResponse,
    ClosedBarRequest,
    DeletedResponse,
    DeleteRefusedResponse,
    DuplicateDeploymentIdentityItem,
    EmaStackEntryItem,
    EnabledChangedResponse,
    EnabledChangeRefusedResponse,
    EnabledRequest,
    EpisodeEntryItem,
    FirstFillConflictResponse,
    FirstFillRecordedResponse,
    FirstFillRequest,
    InternalErrorResponse,
    InvalidDeploymentFileItem,
    LiveResponse,
    NotReadyResponse,
    ReadyResponse,
    RejectedResponse,
    StrategyInstanceItem,
    StrategyInstanceListResponse,
    StrategyInstanceStateNotFoundResponse,
)
from strategy_runtime.runtime.abi_execution_event.models import AbiFirstFillExecutionEvent
from strategy_runtime.runtime.chart_layers.errors import EngineRejected
from strategy_runtime.runtime.chart_layers.models import ChartLayers
from strategy_runtime.runtime.committed_bar_intake import (
    CommittedBarIntakeBoundary,
    IntakeNotAccepting,
)
from strategy_runtime.runtime.enabled_control.errors import EnabledControlRefused
from strategy_runtime.runtime.enabled_control.models import EnabledChangeResult
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.state.errors import StrategyInstanceStateNotFound
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.runtime.strategy_delete.models import DeleteResult
from strategy_runtime.utility.committed_bar import CommittedBarEvent
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
)

FirstFillUseCase = Callable[[AbiFirstFillExecutionEvent], StrategyInstanceRuntimeState]
LoadDeploymentCatalog = Callable[[], DeploymentCatalogSnapshot]
SetStrategyEnabled = Callable[[str, bool], EnabledChangeResult]
DeleteStrategy = Callable[[str], DeleteResult]
GetChartLayers = Callable[[str], ChartLayers]


def create_http_app(
    *,
    ready: bool,
    committed_bar_intake: CommittedBarIntakeBoundary | None,
    process_first_fill: FirstFillUseCase | None,
    load_deployment_catalog: LoadDeploymentCatalog | None = None,
    set_strategy_enabled: SetStrategyEnabled | None = None,
    delete_strategy: DeleteStrategy | None = None,
    get_chart_layers: GetChartLayers | None = None,
    logger: logging.Logger | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    app = FastAPI(title="Strategy Runtime", version="0.1.0", lifespan=lifespan)
    app.state.ready = ready
    app.state.committed_bar_intake = committed_bar_intake
    app.state.process_first_fill = process_first_fill
    app.state.load_deployment_catalog = load_deployment_catalog
    app.state.set_strategy_enabled = set_strategy_enabled
    app.state.delete_strategy = delete_strategy
    app.state.get_chart_layers = get_chart_layers
    app.state.logger = logger or logging.getLogger(__name__)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=RejectedResponse().model_dump(),
        )

    @app.get("/health/live", response_model=LiveResponse)
    async def health_live() -> LiveResponse:
        return LiveResponse()

    @app.get(
        "/health/ready",
        response_model=ReadyResponse | NotReadyResponse,
        responses={503: {"model": NotReadyResponse}},
    )
    async def health_ready() -> ReadyResponse | JSONResponse:
        if app.state.ready:
            return ReadyResponse()
        return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

    @app.post(
        "/v1/webhooks/closed-bar",
        response_model=AcceptedResponse,
        responses={
            400: {"model": RejectedResponse},
            503: {"model": NotReadyResponse},
        },
    )
    async def closed_bar_webhook(
        request: ClosedBarRequest,
    ) -> AcceptedResponse | JSONResponse:
        if not app.state.ready or app.state.committed_bar_intake is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            committed_bar = CommittedBarEvent(
                instrument=request.instrument,
                timeframe=request.timeframe,
                open_time_ms=request.open_time_ms,
            )
            app.state.committed_bar_intake.put_nowait(committed_bar)
        except IntakeNotAccepting:
            app.state.logger.warning(
                "closed-bar rejected: intake_stopping",
                extra={
                    "instrument": committed_bar.instrument,
                    "timeframe": committed_bar.timeframe,
                    "open_time_ms": committed_bar.open_time_ms,
                },
            )
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
        except queue.Full:
            app.state.logger.error(
                "closed-bar rejected: queue_full",
                extra={
                    "instrument": committed_bar.instrument,
                    "timeframe": committed_bar.timeframe,
                    "open_time_ms": committed_bar.open_time_ms,
                    "capacity": app.state.committed_bar_intake.capacity,
                },
            )
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
        except Exception:
            app.state.logger.exception("Failed to accept closed-bar webhook")
            return JSONResponse(status_code=500, content={"status": "error"})

        return AcceptedResponse()

    @app.put(
        "/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill",
        response_model=FirstFillRecordedResponse,
        responses={
            400: {"model": RejectedResponse},
            404: {"model": StrategyInstanceStateNotFoundResponse},
            409: {"model": FirstFillConflictResponse},
            503: {"model": NotReadyResponse},
            500: {"model": InternalErrorResponse},
        },
    )
    def first_fill(
        strategy_instance_id: str,
        trade_cycle_id: str,
        request: FirstFillRequest,
    ) -> FirstFillRecordedResponse | JSONResponse:
        if not app.state.ready or app.state.process_first_fill is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            event = AbiFirstFillExecutionEvent(
                strategy_instance_id=strategy_instance_id,
                trade_cycle_id=trade_cycle_id,
                first_fill_at_ms=request.first_fill_at_ms,
            )
        except ValueError:
            return JSONResponse(status_code=400, content=RejectedResponse().model_dump())

        try:
            app.state.process_first_fill(event)
        except StrategyInstanceStateNotFound:
            return JSONResponse(
                status_code=404, content=StrategyInstanceStateNotFoundResponse().model_dump()
            )
        except FirstFillInvariantError:
            return JSONResponse(status_code=409, content=FirstFillConflictResponse().model_dump())
        except Exception:
            app.state.logger.exception("Failed to process first-fill event")
            return JSONResponse(status_code=500, content=InternalErrorResponse().model_dump())

        return FirstFillRecordedResponse()

    @app.get(
        "/v1/strategy-instances",
        response_model=StrategyInstanceListResponse,
        responses={
            503: {"model": NotReadyResponse | CatalogUnavailableResponse},
            500: {"model": InternalErrorResponse},
        },
    )
    def list_strategy_instances() -> StrategyInstanceListResponse | JSONResponse:
        if not app.state.ready or app.state.load_deployment_catalog is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            snapshot = app.state.load_deployment_catalog()
        except DeploymentCatalogUnavailableError:
            return JSONResponse(status_code=503, content=CatalogUnavailableResponse().model_dump())
        except Exception:
            app.state.logger.exception("Failed to list strategy instances")
            return JSONResponse(status_code=500, content=InternalErrorResponse().model_dump())

        return StrategyInstanceListResponse(
            scanned_file_count=snapshot.scanned_file_count,
            strategy_instances=[
                StrategyInstanceItem(
                    strategy_instance_id=item.strategy_instance_id,
                    strategy_id=item.strategy_id,
                    instrument=item.instrument,
                    base_timeframe=item.base_timeframe,
                    enabled=item.enabled,
                    source_path=item.source_path,
                )
                for item in snapshot.accepted_deployments
            ],
            invalid_files=[
                InvalidDeploymentFileItem(
                    source_path=item.source_path,
                    error_code=item.error_code,
                    error_message=item.error_message,
                )
                for item in snapshot.invalid_files
            ],
            duplicate_identities=[
                DuplicateDeploymentIdentityItem(
                    strategy_instance_id=item.strategy_instance_id,
                    source_paths=list(item.source_paths),
                )
                for item in snapshot.duplicate_identities
            ],
        )

    @app.put(
        "/v1/strategy-instances/{strategy_instance_id}/enabled",
        response_model=EnabledChangedResponse,
        responses={
            400: {"model": RejectedResponse},
            404: {"model": EnabledChangeRefusedResponse},
            409: {"model": EnabledChangeRefusedResponse},
            500: {"model": EnabledChangeRefusedResponse | InternalErrorResponse},
            502: {"model": EnabledChangeRefusedResponse},
            503: {"model": NotReadyResponse | EnabledChangeRefusedResponse},
        },
    )
    def set_strategy_instance_enabled(
        strategy_instance_id: str, request: EnabledRequest
    ) -> EnabledChangedResponse | JSONResponse:
        if not app.state.ready or app.state.set_strategy_enabled is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            result = app.state.set_strategy_enabled(strategy_instance_id, request.enabled)
        except EnabledControlRefused as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=EnabledChangeRefusedResponse(reason=exc.reason).model_dump(),
            )
        except Exception:
            app.state.logger.exception("Failed to change strategy instance enabled")
            return JSONResponse(status_code=500, content=InternalErrorResponse().model_dump())

        return EnabledChangedResponse(
            strategy_instance_id=result.strategy_instance_id,
            enabled=result.enabled,
            cancelled_entry_order=result.cancelled_entry_order,
        )

    @app.delete(
        "/v1/strategy-instances/{strategy_instance_id}",
        response_model=DeletedResponse,
        responses={
            404: {"model": DeleteRefusedResponse},
            409: {"model": DeleteRefusedResponse},
            500: {"model": DeleteRefusedResponse | InternalErrorResponse},
            502: {"model": DeleteRefusedResponse},
            503: {"model": NotReadyResponse | DeleteRefusedResponse},
        },
    )
    def delete_strategy_instance(strategy_instance_id: str) -> DeletedResponse | JSONResponse:
        if not app.state.ready or app.state.delete_strategy is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            result = app.state.delete_strategy(strategy_instance_id)
        except EnabledControlRefused as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=DeleteRefusedResponse(reason=exc.reason).model_dump(),
            )
        except Exception:
            app.state.logger.exception("Failed to delete strategy instance")
            return JSONResponse(status_code=500, content=InternalErrorResponse().model_dump())

        app.state.logger.info(
            "strategy instance %s deleted to %s", result.strategy_instance_id, result.trash_file
        )
        return DeletedResponse(
            strategy_instance_id=result.strategy_instance_id,
            cancelled_entry_order=result.cancelled_entry_order,
            trash_file=result.trash_file,
        )

    @app.get(
        "/v1/strategy-instances/{strategy_instance_id}/chart-layers",
        response_model=ChartLayersResponse,
        responses={
            404: {"model": ChartLayersRefusedResponse},
            422: {"model": ChartLayersRefusedResponse},
            500: {"model": InternalErrorResponse},
            502: {"model": ChartLayersRefusedResponse},
            503: {"model": NotReadyResponse | ChartLayersRefusedResponse},
        },
    )
    def get_strategy_chart_layers(
        strategy_instance_id: str,
    ) -> ChartLayersResponse | JSONResponse:
        if not app.state.ready or app.state.get_chart_layers is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            layers = app.state.get_chart_layers(strategy_instance_id)
        except EnabledControlRefused as exc:
            refused = ChartLayersRefusedResponse(reason=exc.reason)
            if isinstance(exc, EngineRejected):
                refused.engine_code = exc.engine_code
                refused.engine_message = exc.engine_message
            return JSONResponse(
                status_code=exc.status_code,
                content=refused.model_dump(exclude_none=True),
            )
        except Exception:
            app.state.logger.exception("Failed to read strategy chart layers")
            return JSONResponse(status_code=500, content=InternalErrorResponse().model_dump())

        return ChartLayersResponse(
            strategy_instance_id=layers.strategy_instance_id,
            ema_stack=[
                EmaStackEntryItem(
                    role=entry.role,
                    timeframe=entry.timeframe,
                    period=entry.period,
                    source=entry.source,
                )
                for entry in layers.ema_stack
            ],
            episodes=[
                EpisodeEntryItem(episode_ref=entry.episode_ref, params=dict(entry.params))
                for entry in layers.episodes
            ],
        )

    return app
