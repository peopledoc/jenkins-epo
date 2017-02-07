import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from aiohttp.test_utils import make_mocked_coro
from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_url(mocker, SETTINGS):
    throttle_github = mocker.patch(
        'jenkins_epo.procedures.throttle_github', CoroutineMock(),
    )
    Bot = mocker.patch('jenkins_epo.procedures.Bot')
    from_url = mocker.patch(
        'jenkins_epo.procedures.Head.from_url', CoroutineMock()
    )

    from jenkins_epo.procedures import process_url

    bot = Bot.return_value
    bot.run = CoroutineMock()
    head = Mock(sha='cafed0d0')
    head.repository.load_settings = CoroutineMock()
    from_url.return_value = head

    yield from process_url('https://github.com/owner/name/tree/master')

    assert throttle_github.mock_calls
    assert from_url.mock_calls
    assert bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_url_repo_denied(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')
    from_url = mocker.patch(
        'jenkins_epo.procedures.Head.from_url', CoroutineMock()
    )

    from jenkins_epo.procedures import process_url, UnauthorizedRepository

    bot = Bot.return_value
    head = from_url.return_value
    head.sha = 'cafed0d0'
    head.repository.load_settings = CoroutineMock(
        side_effect=UnauthorizedRepository()
    )

    with pytest.raises(UnauthorizedRepository):
        yield from process_url('https://url', throttle=False)

    assert head.repository.load_settings.mock_calls
    assert not bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_url_cancelled(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')
    from_url = mocker.patch(
        'jenkins_epo.procedures.Head.from_url', CoroutineMock()
    )

    from jenkins_epo.procedures import process_url, CancelledError

    bot = Bot.return_value
    bot.run = CoroutineMock(side_effect=CancelledError())
    head = from_url.return_value
    head.sha = 'cafed0d0'
    head.repository.load_settings = CoroutineMock()

    yield from process_url('https://url', throttle=False)

    assert bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_whoami(mocker):
    mocker.patch(
        'jenkins_epo.procedures.cached_arequest',
        make_mocked_coro(return_value=dict(login='aramis')),
    )

    from jenkins_epo import procedures

    login = yield from procedures.whoami()

    assert 'aramis' == login


@patch('jenkins_epo.procedures.Repository.from_name')
def test_list_repositories(from_name, SETTINGS):
    from jenkins_epo import procedures

    SETTINGS.REPOSITORIES = "owner/repo1,owner/repo1"
    repositories = procedures.list_repositories()
    assert 1 == len(list(repositories))


@patch('jenkins_epo.procedures.Repository.from_name')
def test_list_repositories_from_envvar_404(from_name, SETTINGS):
    from jenkins_epo import procedures

    SETTINGS.REPOSITORIES = "owner/repo1 owner/repo1"
    from_name.side_effect = Exception('404')

    repositories = procedures.list_repositories()

    assert 0 == len(list(repositories))


@pytest.mark.asyncio
@asyncio.coroutine
def test_throttle_sleep(mocker, SETTINGS):
    GITHUB = mocker.patch('jenkins_epo.procedures.GITHUB')
    GITHUB.rate_limit.aget = CoroutineMock(return_value=dict())
    compute_throttling = mocker.patch(
        'jenkins_epo.procedures.compute_throttling'
    )
    sleep = mocker.patch(
        'jenkins_epo.procedures.asyncio.sleep', CoroutineMock(name='sleep'),
    )

    from jenkins_epo.procedures import throttle_github

    compute_throttling.return_value = 100

    yield from throttle_github()

    assert sleep.mock_calls


def test_throttling_compute_early(SETTINGS):
    SETTINGS.RATE_LIMIT_THRESHOLD = 0
    from jenkins_epo.procedures import compute_throttling

    remaining = 4900
    seconds = compute_throttling(
        now=Mock(),
        rate_limit=dict(rate=dict(
            limit=5000, remaining=remaining,
        )),
    )
    assert 0 == seconds


def test_throttling_compute_fine(SETTINGS):
    SETTINGS.RATE_LIMIT_THRESHOLD = 0
    from jenkins_epo.procedures import compute_throttling

    # Consumed 1/5 calls at 2/3 of the time.
    now = datetime(2017, 1, 18, 14, 40, tzinfo=timezone.utc)
    reset = datetime(2017, 1, 18, 15, tzinfo=timezone.utc)
    remaining = 4000
    seconds = compute_throttling(
        now=now,
        rate_limit=dict(rate=dict(
            limit=5000, remaining=remaining,
            reset=reset.timestamp(),
        )),
    )
    assert 0 == seconds  # Fine !


def test_throttling_compute_chill(SETTINGS):
    SETTINGS.RATE_LIMIT_THRESHOLD = 0
    from jenkins_epo.procedures import compute_throttling

    # Consumed 4/5 calls at 1/3 of the time.
    seconds = compute_throttling(
        now=datetime(2017, 1, 18, 14, 20, tzinfo=timezone.utc),
        rate_limit=dict(rate=dict(
            limit=5000, remaining=1000,
            reset=datetime(2017, 1, 18, 15, tzinfo=timezone.utc).timestamp(),
        )),
    )

    assert seconds > 0  # Chill !


@pytest.mark.asyncio
@asyncio.coroutine
def test_queue_heads(mocker):
    list_repositories = mocker.patch(
        'jenkins_epo.procedures.list_repositories'
    )
    list_repositories.return_value = []
    whoami = mocker.patch('jenkins_epo.procedures.whoami', CoroutineMock())

    from jenkins_epo.procedures import queue_heads
    from jenkins_epo.compat import PriorityQueue

    yield from queue_heads(PriorityQueue())
    assert list_repositories.mock_calls
    assert whoami.mock_calls


def test_queue_message(mocker):
    process_url = mocker.patch(
        'jenkins_epo.procedures.process_url', CoroutineMock()
    )

    from jenkins_epo.procedures import HeadMessage

    head0 = Mock(url='url://')
    head0.sort_key.return_value = 0
    head1 = Mock(url='url://')
    head1.sort_key.return_value = 1
    msg0 = HeadMessage(head0, me=Mock())
    msg1 = HeadMessage(head1, me=Mock())

    assert str(msg0)
    assert msg0 < msg1
    assert msg0()
    assert process_url.mock_calls
