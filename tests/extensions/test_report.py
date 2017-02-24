import asyncio

from asynctest import Mock
import pytest


def test_pr():
    from jenkins_epo.extensions.core import ReportExtension

    ext = ReportExtension('merger', Mock(name='bot'))
    ext.current = Mock()
    ext.current.head = Mock()
    ext.current.issue_url = None
    ext.current.statuses = {'job1': {'state': 'pending'}}

    assert not ext.failed_build_urls()


def test_pending():
    from jenkins_epo.extensions.core import ReportExtension, Branch

    ext = ReportExtension('merger', Mock(name='bot'))
    ext.current = Mock()
    ext.current.head = Mock(spec=Branch)
    ext.current.issue_url = None
    ext.current.statuses = {'job1': {'state': 'pending'}}

    assert not ext.failed_build_urls()


@pytest.mark.asyncio
@asyncio.coroutine
def test_just_broken():
    from jenkins_epo.repository import Repository
    from jenkins_epo.extensions.core import ReportExtension, Branch

    ext = ReportExtension('merger', Mock(name='bot'))
    ext.current = Mock()
    ext.current.head = Mock(spec=Branch)
    ext.current.head.sha = 'c0defada'
    ext.current.head.ref = 'branch'
    ext.current.repository = Mock(spec=Repository, name='repository')
    ext.current.repository.report_issue.return_value = {
        'html_url': 'https://github.com/owner/name/issues/1',
    }
    ext.current.issue_url = None
    ext.current.commits = [Mock(name='last_commit')]
    ext.bot.parse_instructions.return_value = []
    ext.current.statuses = {
        'job1': {
            'state': 'failure',
            'target_url': 'build_url',
        },
    }

    yield from ext.run()

    assert ext.current.head.comment.mock_calls
    assert ext.current.repository.report_issue.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_reported():
    from jenkins_epo.extensions.core import ReportExtension

    ext = ReportExtension('merger', Mock())
    ext.current = Mock()
    ext.current.issue_url = None

    instruction = Mock(name='instruction', args='https://...')
    instruction.name = 'issue-url'
    ext.process_instruction(instruction)
    assert ext.current.issue_url

    yield from ext.run()

    assert not ext.current.head.comment.mock_calls
    assert not ext.current.repository.report_issue.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_compat():
    from jenkins_epo.extensions.core import ReportExtension

    ext = ReportExtension('merger', Mock())
    ext.current = Mock()
    ext.current.issue_url = None

    instruction = Mock(name='instruction', args='https://...')
    instruction.name = 'report-done'
    ext.process_instruction(instruction)
    assert ext.current.issue_url

    yield from ext.run()

    assert not ext.current.head.comment.mock_calls
    assert not ext.current.repository.report_issue.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_still_broken(mocker):
    Issue = mocker.patch('jenkins_epo.extensions.core.Issue')
    from jenkins_epo.extensions.core import Branch, ReportExtension

    ext = ReportExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = Mock(spec=Branch)
    ext.current.head.sha = 'c0defada'
    ext.current.head.ref = 'branch'
    ext.current.issue_url = None
    ext.current.statuses = {
        'job1': {
            'state': 'failure',
            'target_url': 'build_url',
        },
    }
    broken_commit = Mock(name='broken_commit')
    broken_commit.fetch_comments.return_value = []
    ext.current.commits = [ext.current.last_commit, broken_commit]
    ext.bot.parse_instructions.return_value = instructions = [
        Mock(
            name='instruction', args='https://github.com/owner/name/issues/1'
        ),
    ]
    instructions[0].name = 'issue-url'

    yield from ext.run()

    assert ext.current.head.comment.mock_calls
    assert Issue.from_url.return_value.comment.mock_calls
    assert not ext.current.repository.report_issue.mock_calls
