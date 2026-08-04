"""FastAPI application adapter."""

import logging
from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import Lifespan

from strategy_runtime.adapters.http.models import (
    AcceptedResponse,
    ClosedBarRequest,
    FirstFillConflictResponse,
    FirstFillRecordedResponse,
    FirstFillRequest,
    InternalErrorResponse,
    LiveResponse,
    NotReadyResponse,
    ReadyResponse,
    RejectedResponse,
    StrategyInstanceStateNotFoundResponse,
)
from strategy_runtime.runtime.abi_execution_event.models import AbiFirstFillExecutionEvent
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.state.errors import StrategyInstanceStateNotFound
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.shared.identifiers import IdentifierFactory
from strategy_runtime.utility.committed_bar import CommittedBarEvent

BackgroundUseCase = Callable[[CommittedBarEvent], None]
FirstFillUseCase = Callable[[AbiFirstFillExecutionEvent], StrategyInstanceRuntimeState]


def create_http_app(
    *,
    ready: bool,
    trace_id_factory: IdentifierFactory,
    process_committed_bar: BackgroundUseCase | None,
    process_first_fill: FirstFillUseCase | None,
    logger: logging.Logger | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    app = FastAPI(title="Strategy Runtime", version="0.1.0", lifespan=lifespan)
    app.state.ready = ready
    app.state.process_committed_bar = process_committed_bar
    app.state.process_first_fill = process_first_fill
    app.state.trace_id_factory = trace_id_factory
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
        background_tasks: BackgroundTasks,
    ) -> AcceptedResponse | JSONResponse:
        if not app.state.ready or app.state.process_committed_bar is None:
            return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())

        try:
            committed_bar = CommittedBarEvent(
                instrument=request.instrument,
                timeframe=request.timeframe,
                open_time_ms=request.open_time_ms,
            )
            _trace_id = app.state.trace_id_factory()
            background_tasks.add_task(
                app.state.process_committed_bar,
                committed_bar,
            )
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

    return app
