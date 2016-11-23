from unittest.mock import patch

import pytest
from libfaketime import reexec_if_needed


def pytest_configure():
    reexec_if_needed()


@pytest.fixture
def SETTINGS():
    from jenkins_epo.settings import DEFAULTS, SETTINGS
    patcher = patch.dict('jenkins_epo.settings.SETTINGS', DEFAULTS)
    patcher.start()
    SETTINGS.DEBUG = 0
    yield SETTINGS
    patcher.stop()
