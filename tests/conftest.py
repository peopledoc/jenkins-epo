from unittest.mock import patch

import pytest
from asynctest import CoroutineMock
from libfaketime import reexec_if_needed


def pytest_configure():
    reexec_if_needed()


@pytest.fixture
def SETTINGS():
    from jenkins_epo.settings import DEFAULTS, SETTINGS
    patcher = patch.dict('jenkins_epo.settings.SETTINGS', DEFAULTS)
    patcher.start()
    SETTINGS.DEBUG = 0
    SETTINGS.DRY_RUN = 0
    yield SETTINGS
    patcher.stop()


@pytest.fixture
def WORKERS():
    patcher = patch('jenkins_epo.workers.WORKERS')
    WORKERS = patcher.start()
    WORKERS.enqueue = CoroutineMock()
    WORKERS.queue.join = CoroutineMock()
    yield WORKERS
    patcher.stop()
