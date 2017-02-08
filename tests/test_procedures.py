import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from aiohttp.test_utils import make_mocked_coro
from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_poll(mocker, SETTINGS, WORKERS):
    mocker.patch('jenkins_epo.procedures.WORKERS', WORKERS)
    whoami = mocker.patch('jenkins_epo.procedures.whoami', CoroutineMock())
    asyncio = mocker.patch('jenkins_epo.procedures.asyncio')
    asyncio.sleep = CoroutineMock()

    list_repositories = mocker.patch(
        'jenkins_epo.procedures.list_repositories'
    )
    list_repositories.return_value = [Mock()]

    WORKERS.queue.join.side_effect = [None, ValueError()]
    from jenkins_epo.procedures import poll

    with pytest.raises(ValueError):
        yield from poll()

    assert whoami.mock_calls
    assert list_repositories.mock_calls
    assert asyncio.sleep.mock_calls
    assert WORKERS.queue.join.mock_calls


def test_task_factory():
    from jenkins_epo.procedures import process_task_factory, process_url
    head = Mock()
    head.sort_key.return_value = (1,)
    task = process_task_factory(head)
    assert task.callable_ is process_url


@pytest.mark.asyncio
@asyncio.coroutine
def test_print(mocker, SETTINGS, WORKERS):
    mocker.patch('jenkins_epo.procedures.WORKERS', WORKERS)
    queue_heads = mocker.patch(
        'jenkins_epo.procedures._queue_heads', CoroutineMock(),
    )

    from jenkins_epo.procedures import print_heads

    yield from print_heads()

    assert queue_heads.mock_calls
    assert WORKERS.queue.join.mock_calls


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
    head.url = 'url://test_process_url_repo_denied'
    head.repository.load_settings = CoroutineMock(
        side_effect=UnauthorizedRepository()
    )

    with pytest.raises(UnauthorizedRepository):
        yield from process_url(head.url, throttle=False)

    assert head.repository.load_settings.mock_calls
    assert not bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_url_exclusive(mocker, SETTINGS, event_loop):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')
    from_url = mocker.patch(
        'jenkins_epo.procedures.Head.from_url', CoroutineMock()
    )

    from jenkins_epo.procedures import process_url, _task_map

    bot = Bot.return_value
    bot.run = CoroutineMock()
    head = from_url.return_value
    head.url = 'url://test_process_url_exclusive'
    head.sha = 'cafed0d0'
    head.repository.load_settings = CoroutineMock()

    _task_map[head.url] = running = Mock()
    running.done.return_value = False

    yield from process_url(head.url, throttle=False)

    assert running.cancel.mock_calls
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
