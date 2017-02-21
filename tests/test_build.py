import asyncio
from asynctest import CoroutineMock, Mock
from time import time

import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_from_url(SETTINGS, mocker):
    SETTINGS.JENKINS_URL = 'jenkins://'
    RESTClient = mocker.patch('jenkins_epo.jenkins.RESTClient')

    from jenkins_epo.jenkins import Build, NotOnJenkins

    with pytest.raises(NotOnJenkins):
        yield from Build.from_url('circleci:///')

    RESTClient().aget = CoroutineMock(return_value=dict(number=1))

    build = yield from Build.from_url('jenkins://job/1')

    assert 1 == build.number


def test_props():
    from jenkins_epo.jenkins import Build

    build = Build(job=Mock(), payload={
        'timestamp': 1000 * (time() - 3600 * 4),
        'building': False, 'fullDisplayName': '#1'
    })

    assert build.is_outdated
    assert not build.is_running
    assert str(build)
    assert repr(build)

    with pytest.raises(Exception):
        build.sha

    build = Build(job=Mock(), payload=dict(
        build.payload,
        actions=[{'lastBuiltRevision': {'branch': [{'SHA1': 'cafed0d0'}]}}]
    ))

    assert build.sha == 'cafed0d0'


def test_ref():
    from jenkins_epo.jenkins import Build

    build = Build(job=Mock(), payload={})

    with pytest.raises(Exception):
        build.ref

    build.job.revision_param = 'R'
    build.params['R'] = 'refs/heads/master'

    assert 'master' == build.ref

    build.actions['lastBuiltRevision'] = {
        'branch': [{'name': 'otherremote/master'}]
    }

    with pytest.raises(Exception):
        build.ref

    build.actions['lastBuiltRevision'] = {
        'branch': [{'name': 'refs/remote/origin/master'}]
    }

    assert 'master' == build.ref


def test_params():
    from jenkins_epo.jenkins import Build

    assert 0 == len(Build.process_params({}))
    assert 0 == len(Build.process_params({'actions': [{'parameters': []}]}))
    assert 0 == len(Build.process_params({
        'actions': [{'parameters': [{'name': 'value'}]}]
    }))


def test_future():
    from jenkins_epo.jenkins import Build

    build = Build(job=Mock(), payload={'timestamp': 1000 * (time() + 300)})

    assert not build.is_outdated


def test_commit_status():
    from jenkins_epo.jenkins import Build

    payload = dict(displayName='#3 on master', duration=0, url='url://job/1')
    build = Build(Mock(), payload=dict(payload, result=None))
    assert 'pending' == build.commit_status['state']

    build = Build(Mock(), payload=dict(payload, result='ABORTED'))
    assert 'error' == build.commit_status['state']

    build = Build(Mock(), payload=dict(payload, result='SUCCESS'))
    assert 'success' == build.commit_status['state']

    build = Build(Mock(), payload=dict(payload, result='FAILURE'))
    assert 'failure' == build.commit_status['state']


@pytest.mark.asyncio
@asyncio.coroutine
def test_stop(SETTINGS, mocker):
    RESTClient = mocker.patch('jenkins_epo.jenkins.RESTClient')

    from jenkins_epo.jenkins import Build

    build = Build(Mock(), payload=dict(url='jenkins://'))
    RESTClient().stop.apost = CoroutineMock()

    yield from build.stop()

    assert RESTClient().stop.apost.mock_calls
