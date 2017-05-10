import asyncio

from asynctest import patch, CoroutineMock, Mock
import pytest


def test_lazy_load(mocker):
    Jenkins = mocker.patch('jenkins_epo.jenkins.Jenkins')
    from jenkins_epo.jenkins import JENKINS

    JENKINS.load()

    assert Jenkins.mock_calls
    assert JENKINS._instance


def test_requester(mocker):
    mocker.patch('jenkins_epo.jenkins.Requester.get_url')
    mocker.patch('jenkins_epo.jenkins.Requester.post_url')
    from jenkins_epo.jenkins import VerboseRequester

    VerboseRequester().get_url('url://')
    VerboseRequester().post_url('url://')


def test_enabled():
    from jenkins_epo.jenkins import Job

    assert not Job(Mock(_data=dict(color='disabled'))).enabled
    assert Job(Mock(_data=dict(color='blue'))).enabled


@pytest.mark.asyncio
@asyncio.coroutine
def test_fetch_builds(mocker):
    Client = mocker.patch('jenkins_epo.jenkins.rest.Client')
    Client().api.python.aget = aget = CoroutineMock(
        return_value=dict(builds=[])
    )
    from jenkins_epo.jenkins import Job

    api_instance = Mock(_data=dict())
    api_instance.name = 'freestyle'

    job = Job(api_instance)
    yield from job.fetch_builds()

    assert aget.mock_calls


def test_process_builds():
    from jenkins_epo.jenkins import Job

    api_instance = Mock(_data=dict())
    api_instance.name = 'freestyle'

    job = Job(api_instance)

    builds = list(job.process_builds([
        {'number': 1, 'url': 'url://'},
        {'number': 2, 'url': 'url://'},
    ]))

    assert 2 == len(builds)
    assert 2 == builds[0].number
    assert 1 == builds[1].number


@pytest.mark.asyncio
@asyncio.coroutine
def test_freestyle_build(mocker, SETTINGS):
    JENKINS = mocker.patch('jenkins_epo.jenkins.JENKINS')
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
    job._revision_param = 'R'

    SETTINGS.DRY_RUN = 0
    yield from job.build(pr, spec, 'freestyle')

    assert JENKINS.rest.job().buildWithParameters.apost.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_freestyle_build_dry(mocker, SETTINGS):
    JENKINS = mocker.patch('jenkins_epo.jenkins.JENKINS')

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

    yield from job.build(pr, spec, 'freestyle')

    assert not JENKINS.rest.job().buildWithParameters.apost.mock_calls


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


@pytest.mark.asyncio
@asyncio.coroutine
def test_matrix_build(mocker, SETTINGS):
    JENKINS = mocker.patch('jenkins_epo.jenkins.JENKINS')
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

    yield from job.build(
        Mock(url='url://', fullref='refs/heads/master'), spec, 'matrix',
    )

    assert JENKINS.rest.job().buildWithParameters.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_matrix_build_dry(mocker, SETTINGS):
    JENKINS = mocker.patch('jenkins_epo.jenkins.JENKINS')
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

    yield from job.build(Mock(url='url://'), spec, 'matrix')

    assert not JENKINS.rest.job().buildWithParameters.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_create_job(mocker, SETTINGS):
    from jenkins_epo.jenkins import LazyJenkins

    JENKINS = LazyJenkins(Mock())
    JENKINS.rest = Mock()
    JENKINS.rest.createItem.apost = CoroutineMock()
    JENKINS.rest.job().api.python.aget = CoroutineMock(return_value=dict(
        url='url://', name='job',
    ))
    JENKINS.rest.job()('config.xml').aget = CoroutineMock(
        return_value=Mock(data='<project/>')
    )

    spec = Mock(config=dict())
    spec.name = 'job'

    SETTINGS.DRY_RUN = 1
    job = yield from JENKINS.create_job(spec)

    assert job is None
    assert 'updated_at' in spec.config['description']
    assert not JENKINS.rest.createItem.apost.mock_calls

    SETTINGS.DRY_RUN = 0
    job = yield from JENKINS.create_job(spec)

    assert job
    assert JENKINS.rest.createItem.apost.mock_calls
    assert JENKINS.rest.job().api.python.aget.mock_calls
    assert JENKINS.rest.job()().aget.mock_calls


@patch('jenkins_epo.jenkins.JobSpec.from_xml')
def test_job_managed(from_xml, SETTINGS):
    from jenkins_epo.jenkins import Job

    SETTINGS.JOBS_AUTO = 0

    job = Job(Mock(_data=dict()))
    job.jobs_filter = []
    job._instance.name = 'job'
    job._instance.get_scm_url.return_value = []

    assert job.managed


@pytest.mark.asyncio
@asyncio.coroutine
def test_aget_job(mocker, SETTINGS):
    mocker.patch('jenkins_epo.jenkins.LazyJenkins.load')
    mocker.patch('jenkins_epo.jenkins.Job.factory')

    from jenkins_epo.jenkins import LazyJenkins

    my = LazyJenkins()
    my._instance = Mock()
    my.rest = Mock()
    my.rest.job().api.python.aget = CoroutineMock(return_value=dict(
        url='url://', name='job',
    ))
    my.rest.job()().aget = CoroutineMock()

    job = yield from my.aget_job('name')

    assert job


@pytest.mark.asyncio
@asyncio.coroutine
def test_aget_job_404(mocker, SETTINGS):
    mocker.patch('jenkins_epo.jenkins.LazyJenkins.load')
    mocker.patch('jenkins_epo.jenkins.Job.factory')

    from aiohttp.errors import HttpProcessingError
    from jenkins_epo.jenkins import LazyJenkins, UnknownJob

    my = LazyJenkins()
    my._instance = Mock()
    my.rest = Mock()
    my.rest.job().api.python.aget = CoroutineMock(
        side_effect=HttpProcessingError(code=404)
    )
    my.rest.job()().aget = CoroutineMock()

    with pytest.raises(UnknownJob):
        yield from my.aget_job('name')


@pytest.mark.asyncio
@asyncio.coroutine
def test_update_job(mocker, SETTINGS):
    aget_job = mocker.patch(
        'jenkins_epo.jenkins.JENKINS.aget_job',
        CoroutineMock(),
    )
    rest = mocker.patch('jenkins_epo.jenkins.JENKINS.rest')

    url = rest.job()
    url.api.python.aget = CoroutineMock()
    url().aget = CoroutineMock()
    url().apost = CoroutineMock()

    from jenkins_epo.jenkins import Job

    SETTINGS.DRY_RUN = 1

    spec = Mock(config=dict())
    spec.name = 'job'

    job = Job(Mock(_data=dict()))
    new_job = yield from job.update(spec)
    assert new_job is job

    SETTINGS.DRY_RUN = 0
    new_job = yield from job.update(spec)
    assert new_job is not job
    assert aget_job.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_queue_empty(mocker, SETTINGS):
    from jenkins_epo.jenkins import LazyJenkins

    JENKINS = LazyJenkins(Mock())
    JENKINS.rest = Mock()
    JENKINS.rest.queue.api.python.aget = CoroutineMock(
        return_value=dict(items=[]),
    )

    yield from JENKINS.is_queue_empty()

    assert JENKINS.rest.queue.api.python.aget.mock_calls


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


@pytest.mark.asyncio
@asyncio.coroutine
def test_from_url_removes_suffix(mocker, SETTINGS):
    from jenkins_epo.jenkins import Build
    Client = mocker.patch('jenkins_epo.jenkins.rest.Client')
    Client().api.python.aget = aget = CoroutineMock(
        return_value={}
    )
    SETTINGS.JENKINS_URL = "http://jenkins.local"
    url = SETTINGS.JENKINS_URL + "/job/rh2-build-doc/4910/display/redirect"
    correct_url = SETTINGS.JENKINS_URL + "/job/rh2-build-doc/4910"

    build = yield from Build.from_url(url)

    assert isinstance(build, Build)
    assert build.job is None
    assert build.payload == {}
    assert Client.mock_calls[1] == mocker.call(correct_url)
