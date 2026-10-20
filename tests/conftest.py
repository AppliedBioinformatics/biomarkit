import pytest
import logging
from biomarkit import config


@pytest.fixture(autouse=True)
def active_corpus(tmp_path):
    """
    Gives every test its own empty active corpus under tmp_path, and clears it afterwards so no test leaks corpus
    state into another. Request this fixture by name to get the CorpusPaths for the test's corpus.

    Returns
    -------
    CorpusPaths
    """
    paths = config.set_active_corpus(tmp_path / "corpus")
    yield paths
    config._active_corpus = None


@pytest.fixture(scope="session", autouse=True)
def close_log_handlers_on_test_finish():
    """
    Closes all log handlers after the test session.

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