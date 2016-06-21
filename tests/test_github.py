from unittest.mock import patch, Mock

import pytest


@patch('jenkins_ghp.github.SETTINGS')
@patch('jenkins_ghp.github.GITHUB')
def test_threshold(GITHUB, SETTINGS):
    from jenkins_ghp.project import cached_request, ApiError

    SETTINGS.GHP_RATE_LIMIT_THRESHOLD = 3000
    GITHUB.x_ratelimit_remaining = 2999

    with pytest.raises(ApiError):
        cached_request(Mock())
