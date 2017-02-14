import asyncio
from unittest.mock import Mock

from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_simple(mocker, WORKERS):
    mocker.patch('jenkins_epo.web.WORKERS', WORKERS)
    from jenkins_epo.web import simple_webhook

    req = Mock(GET=dict(head='url://'))
    res = yield from simple_webhook(req)

    assert 200 == res.status
    assert WORKERS.enqueue.mock_calls


def test_signature():
    from jenkins_epo.web import compute_signature
    payload = b"""PAYLOAD"""
    wanted_signature = 'sha1=917eb41141e2e4ce264faa004335e46a344f3f54'
    assert wanted_signature == compute_signature(payload, b'notasecret')


@pytest.mark.asyncio
@asyncio.coroutine
def test_github_webhook_ok(SETTINGS):
    SETTINGS.GITHUB_SECRET = 'notasecret'

    from jenkins_epo.web import github_webhook

    req = Mock()
    req.headers = {
        'X-Hub-Signature': 'sha1=917eb41141e2e4ce264faa004335e46a344f3f54',
    }
    req.read = CoroutineMock(return_value=b"""PAYLOAD""")
    req.release = CoroutineMock()

    res = yield from github_webhook(req)

    assert 200 == res.status


@pytest.mark.asyncio
@asyncio.coroutine
def test_github_webhook_deny(SETTINGS):
    SETTINGS.GITHUB_SECRET = 'notasecret'

    from jenkins_epo.web import github_webhook

    req = Mock()
    req.headers = {'X-Hub-Signature': 'sha1=br04en'}
    req.read = CoroutineMock(return_value=b"""PAYLOAD""")
    req.release = CoroutineMock()

    res = yield from github_webhook(req)

    assert 403 == res.status


@pytest.mark.asyncio
@asyncio.coroutine
def test_register_all(WORKERS, mocker):
    mocker.patch('jenkins_epo.web.WORKERS', WORKERS)
    mocker.patch('jenkins_epo.web.REPOSITORIES', ['owner/repo'])

    from jenkins_epo.web import register_webhook

    yield from register_webhook()


@pytest.mark.asyncio
@asyncio.coroutine
def test_register_task_new(SETTINGS, mocker):
    Repository = mocker.patch('jenkins_epo.web.Repository')
    Repository.from_name = CoroutineMock()
    repo = Repository.from_name.return_value
    repo.fetch_hooks = CoroutineMock()
    repo.process_hooks = Mock(return_value=[])

    from jenkins_epo.web import RegisterTask

    task = RegisterTask('owner/repo')
    yield from task()

    assert Repository.from_name.mock_calls
    assert repo.fetch_hooks.mock_calls
    assert repo.process_hooks.mock_calls
    assert repo.set_hook.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_register_task_update(SETTINGS, mocker):
    SETTINGS.SERVER_URL = 'https://url'
    Repository = mocker.patch('jenkins_epo.web.Repository')
    Repository.from_name = CoroutineMock()
    repo = Repository.from_name.return_value
    repo.fetch_hooks = CoroutineMock()

    from jenkins_epo.web import RegisterTask, WebHook, fullurl

    repo.process_hooks = Mock(return_value=[
        WebHook(dict(
            id='123', name='web', active=True,
            config=dict(
                url=fullurl(route='github-webhook'),
                insecure_ssl="0", content_type="json",
            ),
            events=["commit_comment", "issue_comment", "pull_request"]
        )),
    ])

    task = RegisterTask('owner/repo')
    yield from task()

    assert Repository.from_name.mock_calls
    assert repo.fetch_hooks.mock_calls
    assert repo.process_hooks.mock_calls
    assert repo.set_hook.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_register_task_noop(SETTINGS, mocker):
    SETTINGS.SERVER_URL = 'https://url'

    Repository = mocker.patch('jenkins_epo.web.Repository')
    Repository.from_name = CoroutineMock()
    repo = Repository.from_name.return_value
    repo.fetch_hooks = CoroutineMock()

    from jenkins_epo.web import RegisterTask, WebHook, fullurl

    repo.process_hooks = Mock(return_value=[
        WebHook(dict(
            id='123', name='web',
            active=True,
            config=dict(
                url=fullurl(route='github-webhook'),
                insecure_ssl="0", content_type="json",
            ),
            events=["commit_comment", "issue_comment", "pull_request", "push"],
        )),
    ])

    task = RegisterTask('owner/repo')
    yield from task()

    assert Repository.from_name.mock_calls
    assert repo.fetch_hooks.mock_calls
    assert repo.process_hooks.mock_calls
    assert not repo.set_hook.mock_calls
