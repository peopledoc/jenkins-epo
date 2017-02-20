import asyncio
from asynctest import patch, CoroutineMock, Mock
from time import time

import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_rest_client(mocker):
    ClientSession = mocker.patch('jenkins_epo.jenkins.aiohttp.ClientSession')
    from jenkins_epo.jenkins import RESTClient

    client = RESTClient()
    client = client('http://jenkins/path').subpath

    session = ClientSession.return_value

    response = Mock(name='response')
    session.get = CoroutineMock(return_value=response)
    response.read = CoroutineMock(
        return_value=repr(dict(unittest=True)).encode('utf-8')
    )

    payload = yield from client.aget(param=1)

    assert payload['unittest']


def test_lazy_load(mocker):
    Jenkins = mocker.patch('jenkins_epo.jenkins.Jenkins')
    from jenkins_epo.jenkins import JENKINS

    JENKINS.load()

    assert Jenkins.mock_calls
    assert JENKINS._instance


@pytest.mark.asyncio
@asyncio.coroutine
def test_fetch_builds(mocker):
    RESTClient = mocker.patch('jenkins_epo.jenkins.RESTClient')
    RESTClient().aget = aget = CoroutineMock(return_value=dict(builds=[]))
    from jenkins_epo.jenkins import Job

    api_instance = Mock(_data=dict())
    api_instance.name = 'freestyle'
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = Job(api_instance)
    yield from job.fetch_builds()

    assert aget.mock_calls


def test_process_builds():
    from jenkins_epo.jenkins import Job

    api_instance = Mock(_data=dict())
    api_instance.name = 'freestyle'
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = Job(api_instance)

    builds = list(job.process_builds([
        {'number': 1, 'url': 'url://'},
        {'number': 2, 'url': 'url://'},
    ]))

    assert 2 == len(builds)
    assert 2 == builds[0].buildno
    assert 1 == builds[1].buildno


def test_build_props():
    from jenkins_epo.jenkins import Build

    build = Build(job=Mock(), payload={
        'timestamp': 1000 * (time() - 3600 * 4),
        'building': False,
    }, api_instance=Mock())

    assert build.is_outdated
    assert not build.is_running
    assert str(build)

    with pytest.raises(Exception):
        build.sha

    build.payload['lastBuiltRevision'] = {'branch': {'SHA1': 'cafed0d0'}}
    assert build.sha == 'cafed0d0'


def test_build_ref():
    from jenkins_epo.jenkins import Build

    build = Build(job=Mock(), payload={}, api_instance=Mock())

    with pytest.raises(Exception):
        build.ref

    build.job.revision_param = 'R'
    build.params['R'] = 'refs/heads/master'

    assert 'master' == build.ref

    build.payload['lastBuiltRevision'] = {
        'branch': {'name': 'otherremote/master'}
    }

    with pytest.raises(Exception):
        build.ref

    build.payload['lastBuiltRevision'] = {
        'branch': {'name': 'refs/remote/origin/master'}
    }

    assert 'master' == build.ref


def test_build_params():
    from jenkins_epo.jenkins import Build

    assert 0 == len(Build.process_params({}))
    assert 0 == len(Build.process_params({'actions': [{'parameters': []}]}))
    assert 0 == len(Build.process_params({
        'actions': [{'parameters': [{'name': 'value'}]}]
    }))


def test_build_future():
    from jenkins_epo.jenkins import Build

    build = Build(job=Mock(), payload={'timestamp': 1000 * (time() + 300)})

    assert not build.is_outdated


def test_freestyle_build(SETTINGS):
    from jenkins_epo.jenkins import FreestyleJob

    api_instance = Mock(_data=dict())
    api_instance.name = 'freestyle'
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    pr = Mock(url='url://')
    spec = Mock()
    spec.config = {
        'node': 'slave',
        'parameters': {'PARAM': 'default'},
    }
    job = FreestyleJob(api_instance)
    job._node_param = 'NODE'

    SETTINGS.DRY_RUN = 0
    job.build(pr, spec, 'freestyle')

    assert api_instance.invoke.mock_calls


def test_freestyle_build_dry(SETTINGS):
    from jenkins_epo.jenkins import FreestyleJob

    api_instance = Mock(_data=dict())
    api_instance.name = 'freestyle'
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    pr = Mock(url='url://')
    spec = Mock()
    spec.config = {}
    job = FreestyleJob(api_instance)
    job._node_param = None
    job._revision_param = None

    SETTINGS.DRY_RUN = 1

    job.build(pr, spec, 'freestyle')

    assert not api_instance.invoke.mock_calls


def test_freestyle_node_param():
    from jenkins_epo.jenkins import FreestyleJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance._data = dict()
    api_instance.name = 'freestyle'
    api_instance.get_params.return_value = [
        {'name': 'P', 'type': 'StringParameter'},
        {'name': 'N', 'type': 'LabelParameterDefinition'},
    ]
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = FreestyleJob(api_instance)
    assert 'N' == job.node_param


def test_matrix_combination_param():
    from jenkins_epo.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict()
    api_instance.get_params.return_value = [
        {'name': 'P', 'type': 'StringParameter'},
        {'name': 'C', 'type': 'MatrixCombinationsParameterDefinition'},
    ]

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = MatrixJob(api_instance)
    assert 'C' == job.combination_param


def test_matrix_node_axis():
    from jenkins_epo.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict()

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = MatrixJob(api_instance)

    name_element = Mock()
    name_element.text = 'NODE'
    xml.findall.return_value = [name_element]

    assert 'NODE' == job.node_axis


def test_matrix_list_context_node():
    from jenkins_yml import Job
    from jenkins_epo.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict(activeConfigurations=[
        {'name': 'NODE=slave-legacy,P=a'},
        {'name': 'NODE=slave-ng,P=a'},
        {'name': 'NODE=slave-legacy,P=b'},
        {'name': 'NODE=slave-ng,P=b'},
    ])

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = MatrixJob(api_instance)
    job._node_axis = 'NODE'

    spec = Job('matrix', dict(
        node='slave-ng',
        axis={'P': ['a', 'b', 4.3]},
    ))
    contexts = [c for c in job.list_contexts(spec)]

    assert 2 == len(contexts)
    assert 'NODE=slave-legacy' not in ''.join(contexts)
    assert 'NODE=slave-ng' in ''.join(contexts)


def test_matrix_list_context_node_axis_only():
    from jenkins_yml import Job
    from jenkins_epo.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict(activeConfigurations=[
        {'name': 'NODE=slave,P=a'},
        {'name': 'NODE=slave,P=b'},
    ])

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    job = MatrixJob(api_instance)
    job._node_axis = 'NODE'

    spec = Job('matrix', dict(
        axis={'P': ['a', 'b']}, merged_nodes=['slave'],
    ))
    contexts = [c for c in job.list_contexts(spec)]

    assert 2 == len(contexts)


@patch('jenkins_epo.jenkins.JobSpec')
def test_matrix_list_context_superset(JobSpec):
    from jenkins_yml import Job
    from jenkins_epo.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict(activeConfigurations=[
        {'name': 'A=0,B=a'},
        {'name': 'A=1,B=a'},
        {'name': 'A=0,B=b'},
        {'name': 'A=1,B=b'},
        {'name': 'A=0,B=c'},
        {'name': 'A=1,B=c'},
    ])

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    jenkins_spec = JobSpec.from_xml.return_value
    jenkins_spec.config = dict(axis={'A': [0, 1], 'B': 'abc'})

    job = MatrixJob(api_instance)
    spec = Job('matrix', dict(axis={'B': 'acd'}))

    contexts = [c for c in job.list_contexts(spec)]

    haystack = '\n'.join(contexts)
    assert 'A=0' in haystack
    assert 'A=1' not in haystack
    assert 'B=b' not in haystack
    assert 2 == len(contexts)


def test_matrix_build(SETTINGS):
    from jenkins_epo.jenkins import MatrixJob, JobSpec

    SETTINGS.DRY_RUN = 0

    api_instance = Mock()
    api_instance.name = 'matrix'
    api_instance._data = {'url': 'https://jenkins/job'}
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    spec = JobSpec(api_instance.name)
    spec.config['parameters'] = {'PARAM': 1}

    job = MatrixJob(api_instance)
    job._node_axis = job._revision_param = None
    job._combination_param = 'C'
    job._revision_param = 'R'

    job.build(Mock(url='url://', fullref='refs/heads/master'), spec, 'matrix')

    assert api_instance.invoke.mock_calls


@patch('jenkins_epo.jenkins.requests.post')
def test_matrix_build_dry(post, SETTINGS):
    from jenkins_epo.jenkins import MatrixJob, JobSpec

    SETTINGS.DRY_RUN = 1

    api_instance = Mock()
    api_instance.name = 'matrix'
    api_instance._data = {'url': 'https://jenkins/job'}

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []
    xml.find.return_value = None

    spec = JobSpec(api_instance.name)

    job = MatrixJob(api_instance)
    job._node_axis = job._revision_param = None
    job._combination_param = 'C'

    post.return_value.status_code = 200

    job.build(Mock(url='url://'), spec, 'matrix')

    assert not post.mock_calls


@patch('jenkins_epo.jenkins.Job.factory')
def test_create_job(factory, SETTINGS):
    from jenkins_epo.jenkins import LazyJenkins

    JENKINS = LazyJenkins(Mock())
    spec = Mock(config=dict())

    SETTINGS.DRY_RUN = 1
    JENKINS.create_job(spec)
    assert 'updated_at' in spec.config['description']
    assert not JENKINS._instance.create_job.mock_calls

    SETTINGS.DRY_RUN = 0
    JENKINS.create_job(spec)

    assert JENKINS._instance.create_job.mock_calls
    assert factory.mock_calls


@patch('jenkins_epo.jenkins.JobSpec.from_xml')
def test_job_managed(from_xml, SETTINGS):
    from jenkins_epo.jenkins import Job

    SETTINGS.JOBS_AUTO = 0

    job = Job(Mock(_data=dict()))
    job.jobs_filter = []
    job._instance.name = 'job'
    job._instance.get_scm_url.return_value = []

    assert job.managed


@patch('jenkins_epo.jenkins.LazyJenkins.load')
@patch('jenkins_epo.jenkins.Job.factory')
def test_get_job(factory, load, SETTINGS):
    from jenkins_epo.jenkins import LazyJenkins
    my = LazyJenkins()
    my._instance = Mock()
    my.get_job('name')


@pytest.mark.asyncio
@asyncio.coroutine
def test_aget_job(mocker, SETTINGS):
    mocker.patch('jenkins_epo.jenkins.LazyJenkins.load')
    mocker.patch('jenkins_epo.jenkins.Job.factory')
    RESTClient = mocker.patch('jenkins_epo.jenkins.RESTClient')
    client = RESTClient.return_value
    client.return_value.aget = CoroutineMock()

    from jenkins_epo.jenkins import LazyJenkins
    my = LazyJenkins()
    my._instance = Mock()
    job = yield from my.aget_job('name')

    assert job


@patch('jenkins_epo.jenkins.Job.factory')
def test_update_job(factory, SETTINGS):
    from jenkins_epo.jenkins import LazyJenkins

    SETTINGS.DRY_RUN = 1

    JENKINS = LazyJenkins(Mock())
    spec = Mock(config=dict())
    api_instance = JENKINS._instance.get_job.return_value

    JENKINS.update_job(spec)

    assert not api_instance.update_config.mock_calls
    assert factory.mock_calls

    SETTINGS.DRY_RUN = 0

    JENKINS.update_job(spec)

    assert api_instance.update_config.mock_calls
    assert factory.mock_calls


def test_queue_empty(SETTINGS):
    from jenkins_epo.jenkins import LazyJenkins

    JENKINS = LazyJenkins(Mock())
    JENKINS._instance.get_queue.return_value._data = dict(items=[])

    assert JENKINS.is_queue_empty()


@patch('jenkins_epo.jenkins.JobSpec')
def test_job_updated_at(JobSpec):
    from jenkins_epo.jenkins import Job

    job = Job(Mock(_data=dict(description="""\
Bla bla.

<!--
epo:
  updated_at: 2016-10-10T15:27:00Z
-->
""")))
    assert job.updated_at
    assert 2016 == job.updated_at.year

    job = Job(Mock(_data=dict(description="""no yaml""")))
    assert not job.updated_at
