from datetime import datetime
from unittest.mock import Mock, patch


@patch('jenkins_ghp.repository.cached_request')
def test_from_name(cached_request):
    from jenkins_ghp.repository import Repository

    cached_request.return_value = {
        'clone_url': 'https://github.com/newowner/newname.git'
    }

    repo = Repository.from_name('oldowner', 'oldname')
    assert 'newowner' == repo.owner
    assert 'newname' == repo.name


def test_process_ghp_yml():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    repo.process_settings(ghp_yml=repr(dict(
        branches=['master', 'develop'],
    )))
    wanted = ['refs/heads/master', 'refs/heads/develop']
    assert wanted == repo.SETTINGS.GHP_BRANCHES


@patch('jenkins_ghp.repository.SETTINGS')
def test_process_protected_branches_env(SETTINGS):
    from jenkins_ghp.repository import Repository

    SETTINGS.GHP_REPOSITORIES = 'owner/repo1:master owner/repo2:stable'

    repo = Repository('owner', 'repo1')
    repo.process_settings()
    assert ['refs/heads/master'] == repo.SETTINGS.GHP_BRANCHES


@patch('jenkins_ghp.repository.SETTINGS')
def test_process_protected_branches(SETTINGS):
    from jenkins_ghp.repository import Repository

    SETTINGS.GHP_REPOSITORIES = ''

    repo = Repository('owner', 'repo1')
    repo.process_settings(branches=[
        {'name': 'master'},
    ])
    assert ['refs/heads/master'] == repo.SETTINGS.GHP_BRANCHES


def test_reviewers():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repository')
    repo.process_settings(collaborators=[
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


def test_list_job_specs_from_jenkins():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    repo.jobs = [Mock()]

    jobs = repo.list_job_specs(None)
    assert 1 == len(jobs)


def test_list_job_specs_no_yml():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    jobs = repo.list_job_specs(None)
    assert {} == jobs


def test_list_job_specs_yml():
    from jenkins_ghp.repository import Repository

    repo = Repository('owner', 'repo1')
    jobs = repo.list_job_specs("""
job1: |
    py.test
job2: |
    tox -r
    """.strip())
    assert 2 == len(jobs)


@patch('jenkins_ghp.repository.Head.push_status')
def test_process_status(push_status):
    from jenkins_ghp.repository import Head, CommitStatus

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

    push_status.return_value = None

    head.maybe_update_status(CommitStatus(context='context'))


@patch('jenkins_ghp.repository.Head.push_status')
def test_update_status(push_status):
    from jenkins_ghp.repository import Head, CommitStatus

    head = Head(Mock(), 'master', 'd0d0', None)
    head.statuses = {}
    push_status.return_value = {
        'context': 'job',
        'updated_at': '2016-08-30T08:25:56Z',
    }

    head.maybe_update_status(CommitStatus(context='job', state='success'))

    assert 'job' in head.statuses


def test_filter_contextes():
    from jenkins_ghp.repository import Head

    rebuild_failed = datetime(2016, 8, 11, 16)

    head = Head(Mock(), None, None, None)
    head.statuses = {
        'backed': {'state': 'pending', 'description': 'Backed'},
        'errored': {
            'state': 'error',
            'updated_at': datetime(2016, 8, 11, 10),
        },
        'failed': {
            'state': 'failure',
            'updated_at': datetime(2016, 8, 11, 10),
        },
        'green': {'state': 'success', 'description': 'Success!'},
        'newfailed': {
            'state': 'error',
            'updated_at': datetime(2016, 8, 11, 20),
        },
        'queued': {'state': 'pending', 'description': 'Queued'},
        'running': {'state': 'pending', 'description': 'build #789'},
        'skipped': {
            'state': 'success', 'description': 'Skipped',
            'updated_at': datetime(2016, 8, 11, 10),
        },
    }

    not_built = head.filter_not_built_contexts(
        [
            'backed', 'errored', 'failed', 'green', 'newfailed', 'notbuilt',
            'queued', 'running', 'skipped',
        ],
        rebuild_failed,
    )

    assert 'backed' in not_built
    assert 'errored' in not_built
    assert 'failed' in not_built
    assert 'green' not in not_built
    assert 'newfailed' not in not_built
    assert 'not_built' not in not_built
    assert 'queued' in not_built
    assert 'running' not in not_built
    assert 'skipped' in not_built
