from unittest.mock import Mock, patch


@patch('jenkins_ghp.jenkins.SETTINGS')
def test_freestyle_build(SETTINGS):
    from jenkins_ghp.jenkins import FreestyleJob

    api_instance = Mock()
    api_instance.name = 'freestyle'
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    pr = Mock()
    spec = Mock()
    spec.config = {
        'node': 'slave',
        'parameters': {'PARAM': 'default'},
    }
    job = FreestyleJob(api_instance)
    job._node_param = 'NODE'

    SETTINGS.GHP_DRY_RUN = 0
    job.build(pr, spec, 'freestyle')

    assert api_instance.invoke.mock_calls


def test_freestyle_node_param():
    from jenkins_ghp.jenkins import FreestyleJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'freestyle'
    api_instance.get_params.return_value = [
        {'name': 'P', 'type': 'StringParameter'},
        {'name': 'N', 'type': 'LabelParameterDefinition'},
    ]
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    job = FreestyleJob(api_instance)
    assert 'N' == job.node_param


def test_matrix_combination_param():
    from jenkins_ghp.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance.get_params.return_value = [
        {'name': 'P', 'type': 'StringParameter'},
        {'name': 'C', 'type': 'MatrixCombinationsParameterDefinition'},
    ]

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    job = MatrixJob(api_instance)
    assert 'C' == job.combination_param


def test_matrix_node_axis():
    from jenkins_ghp.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    job = MatrixJob(api_instance)

    name_element = Mock()
    name_element.text = 'NODE'
    xml.findall.return_value = [name_element]

    assert 'NODE' == job.node_axis


def test_matrix_list_context_node():
    from jenkins_yml import Job
    from jenkins_ghp.jenkins import MatrixJob

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

    job = MatrixJob(api_instance)
    job._node_axis = 'NODE'

    spec = Job('matrix', dict(
        node='slave-ng',
        axis={'P': ['a', 'b']},
    ))
    contexts = [c for c in job.list_contexts(spec)]

    assert 2 == len(contexts)
    assert 'NODE=slave-legacy' not in ''.join(contexts)
    assert 'NODE=slave-ng' in ''.join(contexts)


def test_matrix_list_context_node_axis_only():
    from jenkins_yml import Job
    from jenkins_ghp.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict(activeConfigurations=[
        {'name': 'NODE=slave,P=a'},
        {'name': 'NODE=slave,P=b'},
    ])

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    job = MatrixJob(api_instance)
    job._node_axis = 'NODE'

    spec = Job('matrix', dict(
        axis={'P': ['a', 'b']}, merged_nodes=['slave'],
    ))
    contexts = [c for c in job.list_contexts(spec)]

    assert 2 == len(contexts)


@patch('jenkins_ghp.jenkins.JobSpec')
def test_matrix_list_context_superset(JobSpec):
    from jenkins_yml import Job
    from jenkins_ghp.jenkins import MatrixJob

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


@patch('jenkins_ghp.jenkins.Job.factory')
@patch('jenkins_ghp.jenkins.SETTINGS')
def test_create_job(SETTINGS, factory):
    from jenkins_ghp.jenkins import LazyJenkins

    JENKINS = LazyJenkins(Mock())
    spec = Mock()

    SETTINGS.GHP_DRY_RUN = 1
    JENKINS.create_job(spec)

    assert not JENKINS._instance.create_job.mock_calls

    SETTINGS.GHP_DRY_RUN = 0
    JENKINS.create_job(spec)

    assert JENKINS._instance.create_job.mock_calls
    assert factory.mock_calls


@patch('jenkins_ghp.jenkins.Job.factory')
@patch('jenkins_ghp.jenkins.SETTINGS')
def test_update_job(SETTINGS, factory):
    from jenkins_ghp.jenkins import LazyJenkins

    SETTINGS.GHP_DRY_RUN = 1

    JENKINS = LazyJenkins(Mock())
    spec = Mock()
    api_instance = JENKINS._instance.get_job.return_value

    JENKINS.update_job(spec)

    assert not api_instance.update_config.mock_calls
    assert factory.mock_calls

    SETTINGS.GHP_DRY_RUN = 0

    JENKINS.update_job(spec)

    assert api_instance.update_config.mock_calls
    assert factory.mock_calls
