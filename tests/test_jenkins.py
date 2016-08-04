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


def test_matrix_list_context():
    from jenkins_yml import Job
    from jenkins_ghp.jenkins import MatrixJob

    api_instance = Mock(spec=['_get_config_element_tree', 'get_params'])
    api_instance.name = 'matrix'
    api_instance._data = dict(activeConfigurations=[
        {'name': 'P=a,NODE=slave-legacy'},
        {'name': 'P=a,NODE=slave-ng'},
        {'name': 'P=b,NODE=slave-legacy'},
        {'name': 'P=b,NODE=slave-ng'},
    ])

    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    job = MatrixJob(api_instance)

    name_element = Mock()
    name_element.text = 'NODE'
    xml.findall.return_value = [name_element]

    spec = Job('matrix', dict(
        node='slave-ng',
    ))
    contexts = [c for c in job.list_contexts(spec)]

    assert 2 == len(contexts)
    assert 'NODE=slave-legacy' not in ''.join(contexts)
    assert 'NODE=slave-ng' in ''.join(contexts)
