from unittest.mock import patch


@patch('jenkins_ghp.procedures.Repository.load_settings')
@patch('jenkins_ghp.procedures.SETTINGS')
@patch('jenkins_ghp.procedures.JENKINS')
def test_list_repositories(JENKINS, SETTINGS, load_settings):
    from jenkins_ghp import procedures

    JENKINS.get_jobs.return_value = []
    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master"
    repositories = procedures.list_repositories()
    assert 1 == len(list(repositories))

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2"
    repositories = {
        str(p): p
        for p in procedures.list_repositories(with_settings=True)
    }
    assert 2 == len(list(repositories))
    assert 'owner/repo1' in repositories
    assert 'owner/repo2' in repositories
    assert load_settings.mock_calls
