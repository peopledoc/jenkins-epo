import asyncio

from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_wrong_url(mocker):
    from jenkins_epo.repository import Head

    with pytest.raises(Exception):
        yield from Head.from_url('https://github.com/owner/name')


@pytest.mark.asyncio
@asyncio.coroutine
def test_branch_from_url(mocker):
    mocker.patch('jenkins_epo.repository.cached_arequest', CoroutineMock())
    mocker.patch('jenkins_epo.repository.Repository')
    Branch = mocker.patch('jenkins_epo.repository.Branch')

    from jenkins_epo.repository import Head

    head = yield from Head.from_url('https://github.com/own/name/tree/master')
    assert head == Branch.return_value


@pytest.mark.asyncio
@asyncio.coroutine
def test_pr_from_url(mocker):
    mocker.patch('jenkins_epo.repository.cached_arequest', CoroutineMock())
    mocker.patch('jenkins_epo.repository.Repository')
    PullRequest = mocker.patch('jenkins_epo.repository.PullRequest')

    from jenkins_epo.repository import Head

    head = yield from Head.from_url('https://github.com/own/name/pull/1')
    assert head == PullRequest.return_value
