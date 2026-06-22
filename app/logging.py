"""Logging utilities with automatic traceback capture."""
import logging
import traceback

logger = logging.getLogger(__name__)


def log_error_with_trace(message: str, *args, exc: Exception, logger_obj: logging.Logger = None) -> str:
    """Log an error with full traceback and return the formatted traceback string.

    Use instead of ``logger.error("...: %s", exc)`` so the traceback is always
    captured for both the log output and any downstream storage (e.g. book
    metadata).

    Args:
        message: Log message template.
        *args: Format arguments for the message.
        exc: The caught exception.
        logger_obj: Logger to use (defaults to module logger).

    Returns:
        Full traceback as a string, suitable for storing in metadata.
    """
    log = logger_obj or logger
    tb = traceback.format_exc()
    log.error(message, *args, exc_info=True)
    return tb


def log_warning_with_trace(message: str, *args, exc: Exception, logger_obj: logging.Logger = None) -> str:
    """Log a warning with full traceback and return the formatted traceback string."""
    log = logger_obj or logger
    tb = traceback.format_exc()
    log.warning(message, *args, exc_info=True)
    return tb
