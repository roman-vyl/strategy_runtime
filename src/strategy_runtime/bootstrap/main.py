"""Executable Uvicorn entrypoint."""

import logging

import uvicorn

from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.config.loader import load_runtime_config


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    try:
        config = load_runtime_config()
    except ValueError:
        logger.exception("Invalid runtime configuration; refusing to start Runtime")
        raise SystemExit(1) from None

    app = build_application()
    if not app.state.ready:
        logger.error("Runtime composition is not ready; refusing to start Runtime")
        raise SystemExit(1)

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
