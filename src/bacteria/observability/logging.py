import logging
import sys

from loguru import logger

from bacteria.observability.context import get_context


def _context_patcher(record: dict) -> None:
    record["extra"].update(get_context())


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    logger.remove()

    if fmt == "json":
        logger.add(
            sys.stdout,
            level=level,
            serialize=True,
            format="{message}",
            backtrace=False,
            diagnose=False,
        )
    else:
        logger.add(
            sys.stdout,
            level=level,
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan> - "
                "<level>{message}</level>"
                "{extra}"
            ),
            backtrace=True,
            diagnose=True,
        )

    logger.configure(patcher=_context_patcher)

    # Bridge stdlib logging → loguru so SQLAlchemy, uvicorn, etc. go through loguru
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in logging.root.manager.loggerDict:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())
