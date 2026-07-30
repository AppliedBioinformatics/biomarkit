import pytest
import logging
from config import LOG_DIR

@pytest.fixture(scope="session", autouse=True)
def cleanup_logs_on_test_finish():
    """
    Automatically cleans the log folder after each test.

    Returns
    -------
    None
    """
    yield

    # Windows kicks up a fuss on deleting files so explicitly close all log handlers.
    for logger_name in logging.root.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    if LOG_DIR.exists():
        for log_file in LOG_DIR.glob("*.log"):
            try:
                log_file.unlink()
            except OSError:
                # File held open by another process (e.g. a live pipeline run
                # on the active corpus) — leave it in place.
                pass
