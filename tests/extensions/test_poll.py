import asyncio
from unittest.mock import Mock
from time import time

import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_outdated():
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': (time() - 7 * 3600) * 1000}

    yield from ext.run()

    assert not build.is_running.mock_calls
    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_wrong_timezone():
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': (time() + 2 * 3600) * 1000, 'building': False}

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_build_not_running():
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': (time() - 7 * 3600) * 1000, 'building': False}

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_other_branch():
    from time import time
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    ext.current.head.ref = 'branch'
    build = builds[0]
    build._data = {'timestamp': time() * 1000, 'building': True}
    build.get_revision_branch.return_value = [
        {'name': 'refs/remote/origin/other'}
    ]

    yield from ext.run()

    assert build.get_revision_branch.mock_calls
    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_unknown_branch():
    from time import time
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': time() * 1000, 'building': True}
    build.get_revision_branch.return_value = [{'name': 'otherremote/other'}]

    yield from ext.run()

    assert build.get_revision_branch.mock_calls
    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_current_sha():
    from time import time
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.last_commit.sha = 'bab1'
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.list_contexts.return_value = []
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': time() * 1000, 'building': True}
    build.get_revision_branch.return_value = [{'name': 'origin/branch'}]
    build.get_revision.return_value = 'bab1'

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_preset_status_cloning():
    # When Jenkins is cloning, the build is real, we preset status with latest
    # sha.
    from time import time
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.last_commit.sha = 'bab1'
    ext.current.statuses = {}
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.list_contexts.return_value = ['job']
    job.get_builds.return_value = builds = [Mock()]
    job.revision_param = 'R'
    build = builds[0]
    build._data = {
        'timestamp': time() * 1000, 'building': True,
        'actions': [
            {'parameters': [{
                'name': job.revision_param,
                'value': 'refs/heads/branch',
            }]},
        ],
    }
    build.get_revision_branch.return_value = []

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)
    assert ext.current.last_commit.maybe_update_status.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_preset_status_fail():
    from time import time
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.last_commit.sha = 'bab1'
    ext.current.statuses = {}
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.list_contexts.return_value = ['job']
    job.get_builds.return_value = builds = [Mock()]
    job.revision_param = 'R'
    build = builds[0]
    build.get_revision_branch.return_value = []
    # Build with no parameters
    build._data = {
        'timestamp': time() * 1000, 'building': True,
        'actions': [],
    }

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)
    assert not ext.current.last_commit.maybe_update_status.mock_calls

    # Build with no revision param
    ext.current.last_commit.maybe_update_status.reset_mock()
    build._data['actions'].append({'parameters': []})

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)
    assert not ext.current.last_commit.maybe_update_status.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_cancel():
    from time import time
    from jenkins_epo.extensions.jenkins import PollExtension

    ext = PollExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.head.ref = 'branch'
    ext.current.last_commit.sha = 'bab1'
    ext.current.job_specs = {'job': Mock()}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {}
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {
        'url': 'jenkins://running/1',
        'timestamp': time() * 1000,
        'building': True,
    }
    build.get_revision_branch.return_value = [{'name': 'origin/branch'}]
    build.get_revision.return_value = '01d'

    yield from ext.run()

    assert 1 == len(ext.current.cancel_queue)
