import logging
import sys
import structlog

LOG_FILE = "/var/log/esim/app.log"


def configure_logging() -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_FILE))
    except OSError:
        # Local/dev runs without the container's /var/log/esim directory
        # (or without write permission to it) still log to stdout.
        pass

    logging.basicConfig(format="%(message)s", level=logging.INFO, handlers=handlers)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "esim"):
    return structlog.get_logger(name)
