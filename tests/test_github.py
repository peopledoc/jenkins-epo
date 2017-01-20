from datetime import datetime, timedelta, timezone

from asynctest import patch, CoroutineMock, Mock
import pytest


@patch('jenkins_epo.github.GITHUB')
def test_threshold(GITHUB, SETTINGS):
    from jenkins_epo.github import check_rate_limit_threshold, ApiError

    SETTINGS.RATE_LIMIT_THRESHOLD = 3000
    GITHUB.x_ratelimit_remaining = 2999

    with pytest.raises(ApiError):
        check_rate_limit_threshold()


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


@pytest.mark.asyncio
def test_aget(mocker):
    from jenkins_epo.github import CustomGitHub

    aiohttp = mocker.patch('jenkins_epo.github.aiohttp')
    session = aiohttp.ClientSession.return_value
    response = Mock(spec=['headers', 'json'])
    session.get = CoroutineMock(return_value=response)
    response.headers = {}
    response.json = CoroutineMock(return_value={'data': 1})

    GITHUB = CustomGitHub(access_token='cafed0d0')
    res = yield from GITHUB.user.aget()

    assert '_headers' in res
    assert 'data' in res


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


@pytest.mark.asyncio
@patch('jenkins_epo.github.GITHUB')
@patch('jenkins_epo.github.CACHE')
def test_cached_arequest_miss(CACHE, GITHUB, SETTINGS):
    SETTINGS.GITHUB_TOKEN = 'cafec4e3e'
    GITHUB.x_ratelimit_remaining = -1
    from jenkins_epo.github import cached_arequest

    CACHE.get.side_effect = KeyError('key')

    query = Mock(aget=CoroutineMock(return_value='plop'))
    ret = yield from cached_arequest(query)

    assert 'plop' == ret


@pytest.mark.asyncio
@patch('jenkins_epo.github.GITHUB')
@patch('jenkins_epo.github.CACHE')
def test_cached_arequest_no_cache_hit_valid(CACHE, GITHUB, SETTINGS):
    SETTINGS.GITHUB_TOKEN = 'cafec4e3e'
    GITHUB.x_ratelimit_remaining = -1
    from jenkins_epo.github import ApiError, cached_arequest

    cached_data = Mock(_headers={'ETag': 'etagsha'})
    CACHE.get.return_value = cached_data

    query = Mock(aget=CoroutineMock(
        side_effect=ApiError('url', request={}, response=dict(code=304))
    ))
    ret = yield from cached_arequest(query)

    assert cached_data == ret


@pytest.mark.asyncio
@patch('jenkins_epo.github.GITHUB')
@patch('jenkins_epo.github.CACHE')
def test_cached_arequest_error(CACHE, GITHUB, SETTINGS):
    SETTINGS.GITHUB_TOKEN = 'cafec4e3e'
    GITHUB.x_ratelimit_remaining = -1
    from jenkins_epo.github import ApiError, cached_arequest

    CACHE.get.side_effect = KeyError('pouet')

    query = Mock(aget=CoroutineMock(
        side_effect=ApiError('url', request={}, response=dict(code=500))
    ))
    with pytest.raises(ApiError):
        yield from cached_arequest(query)


def test_wait_rate_limit(mocker, SETTINGS):
    sleep = mocker.patch('jenkins_epo.github.time.sleep')
    GITHUB = mocker.patch('jenkins_epo.github.GITHUB')
    from jenkins_epo.github import wait_rate_limit_reset

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    GITHUB.x_ratelimit_reset = (now + timedelta(seconds=500)).timestamp()
    GITHUB.x_ratelimit_remaining = 0

    waited_seconds = wait_rate_limit_reset(now)

    assert sleep.mock_calls
    assert 0 < waited_seconds and waited_seconds < 500
