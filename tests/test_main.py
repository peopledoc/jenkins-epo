from unittest.mock import patch


@patch('jenkins_ghp.main.SETTINGS')
@patch('jenkins_ghp.main.JENKINS')
def test_list_repositories(JENKINS, SETTINGS):
    from jenkins_ghp.main import Procedures

    JENKINS.get_jobs.return_value = []
    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master"
    repositories = Procedures.list_repositories()
    assert 1 == len(list(repositories))

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2"
    repositories = {str(p): p for p in Procedures.list_repositories()}
    assert 2 == len(list(repositories))
    assert 'owner/repo1' in repositories
    assert 'owner/repo2' in repositories
