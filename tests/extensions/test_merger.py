import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock

from asynctest import CoroutineMock
import pytest


def test_detect_wip():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.WIP_TITLE = MergerExtension.SETTINGS['WIP_TITLE']

    ext.current.head.payload = dict(title='WIP bla')
    ext.begin()
    assert True is ext.current.wip

    ext.current.head.payload = dict(title='[WIP] bla')
    ext.begin()
    assert True is ext.current.wip


def test_skip_non_pr():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = object()
    ext.process_opm(Mock())


@pytest.mark.asyncio
@asyncio.coroutine
def test_comment_deny():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = []
    ext.current.last_commit.date = datetime.now()
    ext.current.opm = {}
    ext.current.opm_denied = [Instruction(
        author='noncollaborator', name='opm',
        date=ext.current.last_commit.date + timedelta(hours=1),
    )]

    yield from ext.run()

    assert ext.current.head.comment.mock_calls


def test_deny_non_collaborator():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = []
    ext.current.last_commit.date = datetime.now()
    ext.current.opm = {}
    ext.current.opm_denied = []

    ext.process_instruction(Instruction(
        author='noncollaborator', name='opm',
        date=ext.current.last_commit.date + timedelta(hours=1),
    ))

    assert not ext.current.opm
    assert ext.current.opm_denied


def test_deny_outdated_opm():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = ['collaborator']
    ext.current.last_commit.date = datetime.now()
    ext.current.opm = {}
    ext.current.opm_denied = []

    ext.process_instruction(Instruction(
        author='collaborator', name='opm',
        date=ext.current.last_commit.date - timedelta(hours=1),
    ))

    assert not ext.current.opm


def test_deny_non_collaborator_processed():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = []
    ext.current.last_commit.date = datetime.now()
    ext.current.opm = None
    ext.current.opm_denied = [Instruction(
        author='noncollaborator', name='opm',
    )]

    ext.process_instruction(Instruction(
        author='bot', name='opm-processed',
        date=ext.current.last_commit.date + timedelta(hours=2),
    ))

    assert not ext.current.opm
    assert not ext.current.opm_denied


def test_accept_lgtm():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = ['collaborator']
    ext.current.last_commit.date = commit_date = datetime.now()
    ext.current.opm = None
    ext.current.opm_denied = []

    ext.process_instruction(Instruction(
        author='collaborator', name='opm',
        date=commit_date + timedelta(hours=1),
    ))

    assert 'collaborator' == ext.current.opm.author
    assert not ext.current.opm_denied


@pytest.mark.asyncio
@asyncio.coroutine
def test_merge_wip():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = ['collaborator']
    ext.current.last_commit.date = datetime.now()
    ext.current.opm.author = 'collaborator'
    ext.current.opm.date = datetime.now()
    ext.current.opm_denied = []
    ext.current.opm_processed = None
    ext.current.wip = True

    yield from ext.run()

    assert ext.current.head.comment.mock_calls
    body = ext.current.head.comment.call_args[1]['body']
    assert '@collaborator' in body
    assert not ext.current.head.merge.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_merge_wip_skip_outdated():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = ['collaborator']
    ext.current.last_commit.date = datetime.now()
    ext.current.opm.author = 'collaborator'
    ext.current.opm.date = datetime.now()
    ext.current.opm_denied = []
    ext.current.wip = True
    ext.current.opm_processed = Mock(
        date=ext.current.opm.date + timedelta(minutes=5)
    )

    yield from ext.run()

    assert not ext.current.head.comment.mock_calls
    assert not ext.current.head.merge.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_no_statuses():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.opm = Mock()
    ext.current.opm_denied = []
    ext.current.statuses = {}
    ext.current.wip = None

    yield from ext.run()

    assert not ext.current.head.comment.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_not_green():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.opm = Mock()
    ext.current.opm_denied = []
    ext.current.last_commit.fetch_combined_status = CoroutineMock(
        return_value={'state': 'error'}
    )
    ext.current.wip = None

    yield from ext.run()

    assert not ext.current.head.comment.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_merge_fail():
    from jenkins_epo.extensions.core import MergerExtension, ApiError

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.COLLABORATORS = ['collaborator']
    ext.current.last_commit.date = datetime.now()
    ext.current.opm.author = 'collaborator'
    ext.current.opm_denied = []
    ext.current.wip = None
    ext.current.last_commit.fetch_combined_status = CoroutineMock(
        return_value={'state': 'success'}
    )
    ext.current.head.merge.side_effect = ApiError('url', {}, dict(
        code=405, json=dict(message="error")
    ))

    yield from ext.run()

    assert not ext.current.head.delete_branch.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_merge_success():
    from jenkins_epo.extensions.core import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.opm = Mock(author='author')
    ext.current.opm_denied = []
    ext.current.last_merge_error = None
    ext.current.last_commit.fetch_combined_status = CoroutineMock(
        return_value={'state': 'success'}
    )
    ext.current.wip = None

    yield from ext.run()

    assert ext.current.head.merge.mock_calls
    assert not ext.current.head.comment.mock_calls
    assert ext.current.head.delete_branch.mock_calls
