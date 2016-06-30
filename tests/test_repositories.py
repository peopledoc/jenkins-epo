from unittest.mock import Mock, patch


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


def test_list_jobs_no_yml():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    jobs = repo.list_jobs(None)
    assert [] == jobs


def test_list_jobs_yml():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    jobs = repo.list_jobs("""
job1: |
    py.test
job2: |
    tox -r
    """.strip())
    assert 2 == len(jobs)


def test_process_status():
    from jenkins_ghp.repository import Head

    head = Head(Mock(), 'master', 'd0d0', None)
    head.contexts_filter = []
    head.process_statuses({'statuses': [
        {
            'context': 'job1',
            'state': 'pending',
            'target_url': 'http://jenkins/job/url',
            'updated_at': '2016-06-27T11:58:31Z',
            'description': 'Queued!',
        },
    ]})

    assert 'job1' in head.statuses
