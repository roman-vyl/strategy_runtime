"""FastAPI application adapter."""

import logging
from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from strategy_runtime.adapters.http.models import (
    AcceptedResponse,
    ClosedBarRequest,
    LiveResponse,
    NotReadyResponse,
    ReadyResponse,
    RejectedResponse,
)
from strategy_runtime.shared.identifiers import IdentifierFactory
from strategy_runtime.utility.committed_bar import CommittedBarEvent

BackgroundUseCase = Callable[[CommittedBarEvent], None]


def create_http_app(
    *,
    ready: bool,
    trace_id_factory: IdentifierFactory,
    process_committed_bar: BackgroundUseCase | None,
    logger: logging.Logger | None = None,
) -> FastAPI:
    app = FastAPI(title="Strategy Runtime", version="0.1.0")
    app.state.ready = ready
    app.state.process_committed_bar = process_committed_bar
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

    return app
