import asyncio
from datetime import datetime, timezone
import time
from unittest.mock import Mock, patch

from aiohttp.test_utils import make_mocked_coro
from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_head(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')

    from jenkins_epo.procedures import process_head

    bot = Bot.return_value
    bot.run = CoroutineMock()

    yield from process_head(Mock(sha='cafed0d0'))

    assert bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_head_repo_denied(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')

    from jenkins_epo.procedures import process_head, UnauthorizedRepository

    bot = Bot.return_value
    head = Mock(sha='cafed0d0')
    head.repository.load_settings.side_effect = UnauthorizedRepository()

    with pytest.raises(UnauthorizedRepository):
        yield from process_head(head)

    assert head.repository.load_settings.mock_calls
    assert not bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_head_repo_failed(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')

    from jenkins_epo.procedures import process_head

    bot = Bot.return_value
    head = Mock(sha='cafed0d0')
    head.repository.load_settings.side_effect = ValueError()

    with pytest.raises(ValueError):
        yield from process_head(head)

    assert head.repository.load_settings.mock_calls
    assert not bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_head_cancelled(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')

    from jenkins_epo.procedures import process_head, CancelledError

    bot = Bot.return_value
    bot.run = CoroutineMock(side_effect=CancelledError())

    yield from process_head(Mock(sha='cafed0d0'))

    assert bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_head_log_exception(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')

    from jenkins_epo.procedures import process_head

    bot = Bot.return_value
    bot.run = CoroutineMock(side_effect=ValueError('POUET'))

    yield from process_head(Mock(sha='cafed0d0'))

    assert bot.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_process_head_raise_exception(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.procedures.Bot')
    SETTINGS.DEBUG = 1

    from jenkins_epo.procedures import process_head

    bot = Bot.return_value
    bot.run = CoroutineMock(side_effect=ValueError('POUET'))

    with pytest.raises(ValueError):
        yield from process_head(Mock(sha='cafed0d0'))

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


@patch('jenkins_epo.procedures.list_repositories')
def test_iter_heads_order(list_repositories):
    from jenkins_epo.procedures import iter_heads

    a = Mock()
    branch = Mock(token='a/branch')
    branch.sort_key.return_value = False, 100, 'master'
    a.process_protected_branches.return_value = [branch]
    pr = Mock(token='a/pr')
    pr.sort_key.return_value = False, 50, 'feature'
    a.process_pull_requests.return_value = [pr]
    b = Mock()
    branch = Mock(token='b/branch')
    branch.sort_key.return_value = False, 100, 'master'
    b.process_protected_branches.return_value = [branch]
    pr1 = Mock(token='b/pr1')
    pr1.sort_key.return_value = False, 50, 'feature'
    pr2 = Mock(token='b/pr2')
    pr2.sort_key.return_value = True, 50, 'hotfix'
    b.process_pull_requests.return_value = [pr1, pr2]
    c = Mock()
    c.process_protected_branches.return_value = []
    c.process_pull_requests.return_value = []

    list_repositories.return_value = [a, b, c]

    computed = [h.token for h in iter_heads()]
    wanted = ['a/branch', 'b/pr2', 'a/pr', 'b/branch', 'b/pr1']

    assert wanted == computed


@patch('jenkins_epo.procedures.list_repositories')
def test_iter_heads_close_first(list_repositories):
    from jenkins_epo.procedures import iter_heads

    repo = Mock()
    repo.process_pull_requests.return_value = []
    list_repositories.return_value = [repo]
    branch = Mock(token='repo/branch')
    branch.sort_key.return_value = False, 100, 'master'
    repo.process_protected_branches.return_value = [branch]

    iterator = iter_heads()
    next(iterator)
    iterator.close()


@patch('jenkins_epo.procedures.list_repositories')
def test_iter_heads_close_next(list_repositories):
    from jenkins_epo.procedures import iter_heads

    repo = Mock()
    repo.process_pull_requests.return_value = []
    list_repositories.return_value = [repo]
    master = Mock(token='repo/master')
    master.sort_key.return_value = False, 100, 'master'
    branch = Mock(token='repo/master')
    branch.sort_key.return_value = False, 100, 'master'
    repo.process_protected_branches.return_value = [master, branch]

    iterator = iter_heads()
    next(iterator)
    next(iterator)
    iterator.close()


@pytest.mark.asyncio
@asyncio.coroutine
def test_throttle_sleep(mocker, SETTINGS):
    GITHUB = mocker.patch('jenkins_epo.procedures.GITHUB')
    sleep = mocker.patch(
        'jenkins_epo.procedures.asyncio.sleep', CoroutineMock(name='sleep'),
    )

    from jenkins_epo.procedures import throttle_github

    GITHUB.rate_limit.aget = CoroutineMock(return_value=dict(
        rate=dict(limit=5000, remaining=4000, reset=int(time.time() + 3500))
    ))

    yield from throttle_github()

    assert sleep.mock_calls


def test_throttling_compute(SETTINGS):
    SETTINGS.RATE_LIMIT_THRESHOLD = 0
    from jenkins_epo.procedures import compute_throttling

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

    # Consumed 4/5 calls at 1/3 of the time.
    seconds = compute_throttling(
        now=datetime(2017, 1, 18, 14, 20, tzinfo=timezone.utc),
        rate_limit=dict(rate=dict(
            limit=5000, remaining=1000,
            reset=datetime(2017, 1, 18, 15, tzinfo=timezone.utc).timestamp(),
        )),
    )

    assert seconds > 0  # Chill !
