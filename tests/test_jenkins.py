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
        {'name': 'N', '_class': '...LabelParameterDefinition'},
    ]
    xml = api_instance._get_config_element_tree.return_value
    xml.findall.return_value = []

    job = FreestyleJob(api_instance)
    assert 'N' == job.node_param
