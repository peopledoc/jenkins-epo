import asyncio

from asynctest import CoroutineMock, Mock
import pytest


def test_wrong_url():
    from jenkins_epo.repository import Issue

    with pytest.raises(Exception):
        Issue.from_url(Mock(), 'https://gitlab.com/owner/name/issues/1')


def test_from_url():
    from jenkins_epo.repository import Issue

    issue = Issue.from_url(Mock(), 'https://github.com/owner/name/issues/1')

    assert str(issue)
    assert 1 == issue.number


@pytest.mark.asyncio
@asyncio.coroutine
def test_comment(mocker):
    GITHUB = mocker.patch('jenkins_epo.repository.GITHUB')
    GITHUB.repos().issues().comments.apost = CoroutineMock()
    from jenkins_epo.repository import Issue

    issue = Issue(Mock(), {'number': 1, 'html_url': 'https://url'})

    GITHUB.dry = 1
    yield from issue.comment("Body")
    assert not GITHUB.repos().issues().comments.apost.mock_calls

    GITHUB.dry = 0
    yield from issue.comment("Body")
    assert GITHUB.repos().issues().comments.apost.mock_calls
