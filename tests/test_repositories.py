from unittest.mock import patch


@patch('jenkins_ghp.repository.Repository.fetch_file_contents')
@patch('jenkins_ghp.repository.Repository.fetch_default_settings')
def test_fetch_settings_ghp(fds, ffc):
    from jenkins_ghp.repository import Repository

    fds.return_value = {}
    ffc.return_value = repr(dict(
        branches=['master', 'develop'],
    ))

    repo = Repository('owner', 'repo1')
    repo.fetch_settings()
    wanted = ['refs/heads/master', 'refs/heads/develop']
    assert wanted == repo.SETTINGS.GHP_BRANCHES


@patch('jenkins_ghp.repository.SETTINGS')
@patch('jenkins_ghp.repository.cached_request')
def test_defaults_branches(cached_request, SETTINGS):
    from jenkins_ghp.repository import Repository

    SETTINGS.GHP_REPOSITORIES = 'owner/repo1:master owner/repo2:stable'
    cached_request.return_value = []

    repo = Repository('owner', 'repo1')
    branches = repo.list_watched_branches()
    assert ['refs/heads/master'] == branches


@patch('jenkins_ghp.repository.cached_request')
def test_reviewers(cached_request):
    from jenkins_ghp.repository import Repository

    cached_request.return_value = [
        {'login': 'siteadmin', 'site_admin': True},
        {
            'login': 'contributor',
            'permissions': {'admin': False, 'pull': False, 'push': False},
            'site_admin': False,
        },
        {
            'login': 'pusher',
            'permissions': {'admin': False, 'pull': True, 'push': True},
            'site_admin': False,
        },
        {
            'login': 'owner',
            'permissions': {'admin': True, 'pull': True, 'push': True},
            'site_admin': False,
        },
    ]

    repo = Repository('owner', 'repository')
    reviewers = repo.list_reviewers()

    assert 'siteadmin' in reviewers
    assert 'contributor' not in reviewers
    assert 'pusher' in reviewers
    assert 'owner' in reviewers
