from unittest.mock import patch, Mock

import pytest


@patch('jenkins_ghp.project.SETTINGS')
@patch('jenkins_ghp.project.GITHUB')
def test_threshold(GITHUB, SETTINGS):
    from jenkins_ghp.project import cached_request, ApiError

    SETTINGS.GHP_RATE_LIMIT_THRESHOLD = 3000
    GITHUB.x_ratelimit_remaining = 2999

    with pytest.raises(ApiError):
        cached_request(Mock())


@patch('jenkins_ghp.project.Project.fetch_file_contents')
@patch('jenkins_ghp.project.Project.fetch_default_settings')
def test_fetch_settings_ghp(fds, ffc):
    from jenkins_ghp.project import Project

    fds.return_value = {}
    ffc.return_value = repr(dict(
        branches=['master', 'qualif', 'develop'],
    ))

    project = Project('owner', 'repo1')
    project.fetch_settings()
    assert ['master', 'qualif', 'develop'] == project.SETTINGS.GHP_BRANCHES


@patch('jenkins_ghp.project.SETTINGS')
@patch('jenkins_ghp.project.cached_request')
def test_defaults_branches(cached_request, SETTINGS):
    from jenkins_ghp.project import Project

    SETTINGS.GHP_REPOSITORIES = 'owner/repo1:master owner/repo2:stable'
    cached_request.return_value = []

    project = Project('owner', 'repo1')
    branches = project.list_watched_branches()
    assert ['refs/heads/master'] == branches
