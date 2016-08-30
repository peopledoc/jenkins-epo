from unittest.mock import Mock, patch


@patch('jenkins_ghp.procedures.cached_request')
def test_whoami(cached_request):
    from jenkins_ghp import procedures

    cached_request.return_value = dict(login='aramis')

    assert 'aramis' == procedures.whoami()


@patch('jenkins_ghp.procedures.Repository.from_name')
@patch('jenkins_ghp.procedures.SETTINGS')
@patch('jenkins_ghp.procedures.JENKINS')
def test_list_repositories_from_envvar(JENKINS, SETTINGS, from_name):
    from jenkins_ghp import procedures

    JENKINS.get_jobs.return_value = []

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master owner/repo1"
    repositories = procedures.list_repositories()
    assert 1 == len(list(repositories))


@patch('jenkins_ghp.procedures.Repository.from_name')
@patch('jenkins_ghp.procedures.SETTINGS')
@patch('jenkins_ghp.procedures.JENKINS')
def test_list_repositories_with_settings(JENKINS, SETTINGS, from_name):
    from jenkins_ghp import procedures

    from_name.side_effect = reps = [Mock(), Mock()]
    reps[0].__str__ = lambda x: 'owner/repo1'
    reps[1].__str__ = lambda x: 'owner/repo2'

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2"
    repositories = {
        str(p): p
        for p in procedures.list_repositories(with_settings=True)
    }
    assert 2 == len(list(repositories))
    assert 'owner/repo1' in repositories
    assert reps[0].load_settings.mock_calls
    assert 'owner/repo2' in repositories
    assert reps[1].load_settings.mock_calls


@patch('jenkins_ghp.procedures.Repository.from_name')
@patch('jenkins_ghp.procedures.SETTINGS')
@patch('jenkins_ghp.procedures.JENKINS')
def test_list_repositories_from_jenkins(JENKINS, SETTINGS, from_name):
    from jenkins_ghp import procedures

    from_name.side_effect = [Mock()]
    job = Mock()
    job.get_scm_url.return_value = ['https://github.com/owner/repo.git']
    JENKINS.get_jobs.return_value = [job]

    SETTINGS.GHP_REPOSITORIES = ""
    repositories = procedures.list_repositories()
    assert 1 == len(list(repositories))
