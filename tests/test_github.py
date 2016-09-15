from unittest.mock import patch, Mock

import pytest


@patch('jenkins_epo.github.SETTINGS')
@patch('jenkins_epo.github.GITHUB')
def test_threshold(GITHUB, SETTINGS):
    from jenkins_epo.github import cached_request, ApiError

    SETTINGS.RATE_LIMIT_THRESHOLD = 3000
    GITHUB.x_ratelimit_remaining = 2999

    with pytest.raises(ApiError):
        cached_request(Mock())


@patch('jenkins_epo.github.CustomGitHub._process_resp')
@patch('jenkins_epo.github.build_opener')
def test_log_reset(build_opener, _process_resp):
    from jenkins_epo.github import CustomGitHub

    GITHUB = CustomGitHub()
    GITHUB.x_ratelimit_remaining = 4000

    def process_resp_se(*a, **kw):
        GITHUB.x_ratelimit_remaining += 10
    _process_resp.side_effect = process_resp_se

    GITHUB.user.get()

    assert _process_resp.mock_calls


@patch('jenkins_epo.github.SETTINGS')
@patch('jenkins_epo.github.CACHE')
def test_cached_request_etag(CACHE, SETTINGS):
    from jenkins_epo.github import cached_request

    SETTINGS.GITHUB_TOKEN = 'cafec4e3e'

    CACHE.get.return_value = response = Mock()
    response._headers = {'ETag': 'e1ag'}
    query = Mock()
    cached_request(query)

    headers = query.get.mock_calls[0][2]['headers']
    assert b'If-None-Match' in headers
