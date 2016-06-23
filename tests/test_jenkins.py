from unittest.mock import patch


@patch('jenkins_ghp.jenkins.Jenkins')
@patch('jenkins_ghp.jenkins.SETTINGS')
def test_list_repositories(SETTINGS, Jenkins):
    from jenkins_ghp.jenkins import JENKINS

    Jenkins.return_value.get_jobs.return_value = []

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master"
    repositories = JENKINS.list_repositories()
    assert 1 == len(repositories)

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2:"
    repositories = {str(p): p for p in JENKINS.list_repositories()}
    assert 2 == len(repositories)
    assert 'owner/repo1' in repositories
    assert 'owner/repo2' in repositories
