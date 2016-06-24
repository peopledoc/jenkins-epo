from unittest.mock import patch


@patch('jenkins_ghp.repository.SETTINGS')
def test_list_repositories(SETTINGS):
    from jenkins_ghp.repository import Repository

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master"
    repositories = Repository.from_jobs()
    assert 1 == len(repositories)

    SETTINGS.GHP_REPOSITORIES = "owner/repo1:master,stable owner/repo2"
    repositories = {str(p): p for p in Repository.from_jobs()}
    assert 2 == len(repositories)
    assert 'owner/repo1' in repositories
    assert 'owner/repo2' in repositories


def test_load_ghp_yml():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    repo.load_settings(ghp_yml=repr(dict(
        branches=['master', 'develop'],
    )))
    wanted = ['refs/heads/master', 'refs/heads/develop']
    assert wanted == repo.SETTINGS.GHP_BRANCHES


@patch('jenkins_ghp.repository.SETTINGS')
def test_load_protected_branches_env(SETTINGS):
    from jenkins_ghp.repository import Repository

    SETTINGS.GHP_REPOSITORIES = 'owner/repo1:master owner/repo2:stable'

    repo = Repository('owner', 'repo1')
    repo.load_settings()
    assert ['refs/heads/master'] == repo.SETTINGS.GHP_BRANCHES


@patch('jenkins_ghp.repository.SETTINGS')
def test_load_protected_branches(SETTINGS):
    from jenkins_ghp.repository import Repository

    SETTINGS.GHP_REPOSITORIES = ''

    repo = Repository('owner', 'repo1')
    repo.load_settings(branches=[
        {'name': 'master'},
    ])
    assert ['refs/heads/master'] == repo.SETTINGS.GHP_BRANCHES


def test_reviewers():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repository')
    repo.load_settings(collaborators=[
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
    ])

    reviewers = repo.SETTINGS.GHP_REVIEWERS

    assert 'siteadmin' in reviewers
    assert 'contributor' not in reviewers
    assert 'pusher' in reviewers
    assert 'owner' in reviewers
