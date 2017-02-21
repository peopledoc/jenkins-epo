import asyncio
from unittest.mock import Mock

from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_skip_outdated():
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.head.sha = 'cafed0d0'
    ext.current.cancel_queue = []
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.fetch_builds = CoroutineMock()
    job.process_builds.return_value = builds = [Mock()]
    build = builds[0]
    build.is_outdated = True

    yield from ext.run()

    assert not builds[0].is_running.mock_calls
    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_skip_build_not_running():
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.head.sha = 'cafed0d0'
    ext.current.cancel_queue = []
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.fetch_builds = CoroutineMock()
    job.process_builds.return_value = builds = [Mock()]
    build = builds[0]
    build.is_outdated = False
    build.is_running = False

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_skip_other_branch():
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.sha = 'cafed0d0'
    ext.current.head.ref = 'branch'
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.fetch_builds = CoroutineMock()
    job.process_builds.return_value = builds = [Mock()]
    build = builds[0]
    build.is_outdated = False
    build.is_running = True
    build.ref = 'otherbranch'

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_skip_current_sha(mocker):
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.head.sha = 'bab1'
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.list_contexts.return_value = []
    job.fetch_builds = CoroutineMock()
    job.process_builds.return_value = builds = [Mock()]
    build = builds[0]
    build.is_outdated = False
    build.is_running = True
    build.ref = 'branch'
    build.sha = ext.current.head.sha

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_preset_status_cloning(mocker):
    # When Jenkins is cloning, the build is real but no status is reported, we
    # preset status on latest sha.
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock(name='bot'))
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.head.sha = 'bab1'
    ext.current.last_commit.maybe_update_status = CoroutineMock()
    ext.current.statuses = {}
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.list_contexts.return_value = ['job']
    job.fetch_builds = CoroutineMock()
    job.process_builds.return_value = builds = [Mock(spec=[
        'is_outdated', 'is_running', 'ref', 'url'
    ])]
    build = builds[0]
    build.is_outdated = False
    build.is_running = True
    build.ref = 'branch'
    build.commit_status = dict()
    build.url = 'url://'

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)
    assert ext.current.last_commit.maybe_update_status.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_cancel(mocker):
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.head.sha = 'bab1'
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.fetch_builds = CoroutineMock()
    job.process_builds.return_value = builds = [Mock()]
    build = builds[0]
    build.is_outdated = False
    build.is_running = True
    build.ref = 'branch'
    build.sha = '01d'
    build.url = 'url://'
    build.commit_status = dict()

    yield from ext.run()

    assert 1 == len(ext.current.cancel_queue)
