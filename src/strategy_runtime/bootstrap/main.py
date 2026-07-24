"""Executable Uvicorn entrypoint."""

import logging

import uvicorn

from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.config.loader import load_runtime_config

app = build_application()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        config = load_runtime_config()
        host = config.host
        port = config.port
    except ValueError:
        logging.getLogger(__name__).exception(
            "Invalid runtime configuration; starting not-ready HTTP service on local defaults"
        )
        host = "127.0.0.1"
        port = 8093
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
