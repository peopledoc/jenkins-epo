import asyncio
from unittest.mock import Mock
from time import time

import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_outdated():
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
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
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
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
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
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
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.jobs = {}
    ext.current.head.ref = 'branch'

    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': time() * 1000, 'building': True}
    build.get_revision_branch.return_value = [{'name': 'origin/other'}]

    yield from ext.run()

    assert build.get_revision_branch.mock_calls
    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_missing_revision():
    from time import time
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.jobs = {}
    ext.current.head.ref = 'branch'

    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': time() * 1000, 'building': True}
    build.get_revision_branch.side_effect = IndexError(0)

    yield from ext.run()

    assert build.get_revision_branch.mock_calls
    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_skip_current_sha():
    from time import time
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.jobs = {}
    ext.current.head.ref = 'branch'
    ext.current.last_commit.sha = 'bab1'
    ext.current.jobs['job'] = job = Mock()
    job.get_builds.return_value = builds = [Mock()]
    build = builds[0]
    build._data = {'timestamp': time() * 1000, 'building': True}
    build.get_revision_branch.return_value = [{'name': 'origin/branch'}]
    build.get_revision.return_value = 'bab1'

    yield from ext.run()

    assert 0 == len(ext.current.cancel_queue)


@pytest.mark.asyncio
@asyncio.coroutine
def test_jenkins_cancel():
    from time import time
    from jenkins_epo.extensions.jenkins import AutoCancelExtension

    ext = AutoCancelExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.jobs = {}
    ext.current.head.ref = 'branch'
    ext.current.last_commit.sha = 'bab1'
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
