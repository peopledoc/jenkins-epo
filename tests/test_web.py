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


def test_compute_signature():
    from jenkins_epo.web import compute_signature
    payload = b"""PAYLOAD"""
    wanted_signature = 'sha1=917eb41141e2e4ce264faa004335e46a344f3f54'
    assert wanted_signature == compute_signature(payload, b'notasecret')


@pytest.mark.asyncio
@asyncio.coroutine
def test_github_webhook_ok(mocker, SETTINGS, WORKERS):
    SETTINGS.GITHUB_SECRET = 'notasecret'
    validate = mocker.patch('jenkins_epo.web.validate_signature')
    infer = mocker.patch('jenkins_epo.web.infer_url_from_event')
    mocker.patch('jenkins_epo.web.WORKERS', WORKERS)

    from jenkins_epo.web import github_webhook

    req = Mock()
    req.read = CoroutineMock(return_value=b"""{"payload": null}""")
    req.release = CoroutineMock()

    res = yield from github_webhook(req)

    assert validate.mock_calls
    assert infer.mock_calls
    assert WORKERS.enqueue.mock_calls
    assert 200 == res.status


@pytest.mark.asyncio
@asyncio.coroutine
def test_github_webhook_deny(mocker, SETTINGS, WORKERS):
    SETTINGS.GITHUB_SECRET = 'notasecret'
    validate = mocker.patch('jenkins_epo.web.validate_signature')
    infer = mocker.patch('jenkins_epo.web.infer_url_from_event')
    mocker.patch('jenkins_epo.web.WORKERS', WORKERS)

    from jenkins_epo.web import github_webhook, DenySignature

    req = Mock()
    req.read = CoroutineMock(return_value=b"""PAYLOAD""")
    req.release = CoroutineMock()

    validate.side_effect = DenySignature()

    res = yield from github_webhook(req)

    assert validate.mock_calls
    assert not infer.mock_calls
    assert not WORKERS.enqueue.mock_calls
    assert 403 == res.status


@pytest.mark.asyncio
@asyncio.coroutine
def test_github_webhook_unknown(mocker, SETTINGS, WORKERS):
    SETTINGS.GITHUB_SECRET = 'notasecret'
    validate = mocker.patch('jenkins_epo.web.validate_signature')
    infer = mocker.patch('jenkins_epo.web.infer_url_from_event')
    mocker.patch('jenkins_epo.web.WORKERS', WORKERS)

    from jenkins_epo.web import github_webhook, SkipEvent

    req = Mock()
    req.read = CoroutineMock(return_value=b'''{"payload": null}''')
    req.release = CoroutineMock()

    infer.side_effect = SkipEvent()

    res = yield from github_webhook(req)

    assert validate.mock_calls
    assert infer.mock_calls
    assert not WORKERS.enqueue.mock_calls
    assert 200 == res.status


def test_github_validate_no_secret(mocker, SETTINGS):
    SETTINGS.GITHUB_SECRET = None
    from jenkins_epo.web import validate_signature, DenySignature

    with pytest.raises(DenySignature):
        validate_signature(headers={}, payload=b'{"payload"}')


def test_github_validate_deny_missing_header(SETTINGS):
    SETTINGS.GITHUB_SECRET = 'notasecret'
    from jenkins_epo.web import validate_signature, DenySignature

    with pytest.raises(DenySignature):
        validate_signature(headers={}, payload=b'{"payload"}')


def test_github_validate_deny_wrong(SETTINGS):
    SETTINGS.GITHUB_SECRET = 'notasecret'
    from jenkins_epo.web import validate_signature, DenySignature

    with pytest.raises(DenySignature):
        validate_signature(
            headers={'X-Hub-Signature': 'sha1=d0d0cafec0041edeadbeef'},
            payload=b'{"payload"}',
        )


def test_github_validate_ok(mocker, SETTINGS):
    compute = mocker.patch('jenkins_epo.web.compute_signature')
    SETTINGS.GITHUB_SECRET = 'notasecret'
    from jenkins_epo.web import validate_signature

    compute.return_value = 'sha1=d0d0cafec0041edeadbeef'

    assert validate_signature(
        headers={'X-Hub-Signature': 'sha1=d0d0cafec0041edeadbeef'},
        payload=b'{"payload"}',
    )


def test_infer_pr_opened():
    from jenkins_epo.web import infer_url_from_event

    assert infer_url_from_event({
        'action': 'opened',
        'pull_request': {
            'html_url': 'https://url',
        }
    })


def test_infer_pr_closed():
    from jenkins_epo.web import infer_url_from_event, SkipEvent

    with pytest.raises(SkipEvent):
        infer_url_from_event({
            'action': 'closed', 'pull_request': {}
        })


def test_infer_pr_comment():
    from jenkins_epo.web import infer_url_from_event

    assert infer_url_from_event({
        'issue': {'pull_request': {'html_url': 'https://url'}},
    })


def test_infer_issue_comment():
    from jenkins_epo.web import infer_url_from_event, SkipEvent

    with pytest.raises(SkipEvent):
        infer_url_from_event({'issue': {}})


def test_infer_branch_push():
    from jenkins_epo.web import infer_url_from_event

    url = infer_url_from_event({
        'ref': 'refs/heads/master',
        'repository': {'html_url': 'https://url'}
    })

    assert '/tree/master' in url


def test_infer_unknown():
    from jenkins_epo.web import infer_url_from_event, SkipEvent

    with pytest.raises(SkipEvent):
        infer_url_from_event({})


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
            events=["issue_comment", "pull_request"]
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
            events=["issue_comment", "pull_request", "push"],
        )),
    ])

    task = RegisterTask('owner/repo')
    yield from task()

    assert Repository.from_name.mock_calls
    assert repo.fetch_hooks.mock_calls
    assert repo.process_hooks.mock_calls
    assert not repo.set_hook.mock_calls
