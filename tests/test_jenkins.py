from unittest.mock import patch


@patch('jenkins_ghp.jenkins.Jenkins')
@patch('jenkins_ghp.jenkins.SETTINGS')
def test_list_projects(SETTINGS, Jenkins):
    from jenkins_ghp.jenkins import JENKINS

    Jenkins.return_value.get_jobs.return_value = []

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master"
    projects = JENKINS.list_projects()
    assert 1 == len(projects)

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2:"
    projects = {str(p): p for p in JENKINS.list_projects()}
    assert 2 == len(projects)
    assert 'owner/repo1' in projects
    assert 'owner/repo2' in projects
