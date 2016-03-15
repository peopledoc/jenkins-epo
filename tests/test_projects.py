from unittest.mock import patch, Mock

import pytest


@patch('jenkins_ghp.project.SETTINGS')
def test_list_projects(SETTINGS):
    from jenkins_ghp.project import Project

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master"
    Project._repositories_settings = None
    projects = [p for p in Project.list_projects()]
    assert 'owner/repo1' in Project._repositories_settings
    assert 1 == len(projects)

    Project._repositories_settings = None
    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2:"
    projects = {str(p): p for p in Project.list_projects()}
    assert 2 == len(projects)
    assert 'owner/repo1' in Project._repositories_settings
    assert (
        ['refs/heads/master', 'refs/heads/stable'] ==
        Project._repositories_settings['owner/repo1']
    )
    assert 'owner/repo2' in Project._repositories_settings
    assert [] == Project._repositories_settings['owner/repo2']

    assert (
        ['refs/heads/master', 'refs/heads/stable'] ==
        projects['owner/repo1'].branches_settings()
    )


@patch('jenkins_ghp.project.SETTINGS')
@patch('jenkins_ghp.project.GITHUB')
def test_threshold(GITHUB, SETTINGS):
    from jenkins_ghp.project import cached_request, ApiError

    SETTINGS.GHP_RATE_LIMIT_THRESHOLD = 3000
    GITHUB.x_ratelimit_remaining = 2999

    with pytest.raises(ApiError):
        cached_request(Mock())
