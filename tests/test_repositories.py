from datetime import datetime
from unittest.mock import Mock, patch

import pytest


@patch('jenkins_epo.repository.cached_request')
def test_from_name(cached_request):
    from jenkins_epo.repository import Repository

    cached_request.return_value = {
        'owner': {'login': 'newowner'},
        'name': 'newname',
    }

    repo = Repository.from_name('oldowner', 'oldname')
    assert 'newowner' == repo.owner
    assert 'newname' == repo.name


@patch('jenkins_epo.repository.cached_request')
def test_from_remote(cached_request):
    from jenkins_epo.repository import Repository

    with pytest.raises(ValueError):
        Repository.from_remote('https://git.lan/project.git')

    assert not cached_request.mock_calls

    cached_request.return_value = {
        'owner': {'login': 'newowner'},
        'name': 'newname',
    }

    repo = Repository.from_remote('https://github.com/owner/project.git')
    assert 'newowner' == repo.owner
    assert 'newname' == repo.name


@patch('jenkins_epo.repository.cached_request')
@patch('jenkins_epo.repository.Branch')
@patch('jenkins_epo.repository.SETTINGS')
def test_load_branches(SETTINGS, Branch, cached_request):
    from jenkins_epo.repository import Repository

    repo = Repository('owner', 'name')
    repo.SETTINGS.BRANCHES = ['refs/heads/master']

    heads = list(repo.load_branches())

    assert 1 == len(heads)
    assert Branch.return_value == heads[0]


@patch('jenkins_epo.repository.cached_request')
@patch('jenkins_epo.repository.PullRequest')
@patch('jenkins_epo.repository.SETTINGS')
def test_load_pulls(SETTINGS, PullRequest, cached_request):
    from jenkins_epo.repository import Repository

    cached_request.return_value = [dict(html_url='/123')]
    repo = Repository('owner', 'name')

    heads = list(repo.load_pulls())

    assert 1 == len(heads)
    assert PullRequest.return_value == heads[0]


@patch('jenkins_epo.repository.cached_request')
@patch('jenkins_epo.repository.PullRequest')
@patch('jenkins_epo.repository.SETTINGS')
def test_load_pulls_filtered(SETTINGS, PullRequest, cached_request):
    from jenkins_epo.repository import Repository

    cached_request.return_value = [dict(
        head=dict(ref='pr'),
        html_url='nomatch',
    )]
    repo = Repository('owner', 'name')
    repo.pr_filter = ['match*']

    heads = list(repo.load_pulls())

    assert 0 == len(heads)


@patch('jenkins_epo.repository.GITHUB')
@patch('jenkins_epo.repository.cached_request')
def test_load_settings_no_yml(cached_request, GITHUB):
    from jenkins_epo.repository import ApiNotFoundError, Repository

    GITHUB.fetch_file_contents.side_effect = ApiNotFoundError(
        'url', Mock(), Mock())

    repo = Repository('owner', 'repo1')
    repo.load_settings()

    assert cached_request.mock_calls


@patch('jenkins_epo.repository.GITHUB')
@patch('jenkins_epo.repository.cached_request')
def test_load_settings_jenkins_yml(cached_request, GITHUB):
    from jenkins_epo.repository import Repository

    GITHUB.fetch_file_contents.side_effect = [
        repr(dict(settings=dict(branches=['master'], reviewers=['octo']))),
    ]

    repo = Repository('owner', 'repo1')
    repo.load_settings()

    assert not cached_request.mock_calls


def test_process_jenkins_yml_settings():
    from jenkins_epo.repository import Repository

    repo = Repository('owner', 'repo1')
    repo.process_settings(
        jenkins_yml=repr(dict(settings=dict(branches=['master', 'develop']))),
    )
    wanted = ['refs/heads/master', 'refs/heads/develop']
    assert wanted == repo.SETTINGS.BRANCHES


@patch('jenkins_epo.repository.SETTINGS')
def test_process_protected_branches_env(SETTINGS):
    from jenkins_epo.repository import Repository

    SETTINGS.REPOSITORIES = 'owner/repo1:master owner/repo2:stable'

    repo = Repository('owner', 'repo1')
    repo.process_settings()
    assert ['refs/heads/master'] == repo.SETTINGS.BRANCHES


@patch('jenkins_epo.repository.SETTINGS')
def test_process_protected_branches(SETTINGS):
    from jenkins_epo.repository import Repository

    SETTINGS.REPOSITORIES = ''

    repo = Repository('owner', 'repo1')
    repo.process_settings(branches=[
        {'name': 'master'},
    ])
    assert ['refs/heads/master'] == repo.SETTINGS.BRANCHES


def test_reviewers():
    from jenkins_epo.repository import Repository

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

    reviewers = repo.SETTINGS.REVIEWERS

    assert 'siteadmin' in reviewers
    assert 'contributor' not in reviewers
    assert 'pusher' in reviewers
    assert 'owner' in reviewers


@patch('jenkins_epo.repository.Head.push_status')
def test_process_status(push_status):
    from jenkins_epo.repository import Head, CommitStatus

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


@patch('jenkins_epo.repository.Head.push_status')
def test_update_status(push_status):
    from jenkins_epo.repository import Head, CommitStatus

    head = Head(Mock(), 'master', 'd0d0', None)
    head.statuses = {}
    push_status.return_value = {
        'context': 'job',
        'updated_at': '2016-08-30T08:25:56Z',
    }

    head.maybe_update_status(CommitStatus(context='job', state='success'))

    assert 'job' in head.statuses


@patch('jenkins_epo.repository.GITHUB')
def test_push_status_dry(GITHUB):
    from datetime import datetime
    from jenkins_epo.repository import Head, CommitStatus

    GITHUB.dry = 1

    head = Head(Mock(), 'master', 'd0d0', None)
    head.statuses = {}
    status = head.push_status(CommitStatus(
        context='job', state='success', description='desc',
        updated_at=datetime(2016, 9, 13, 13, 41, 00),
    ))
    assert isinstance(status['updated_at'], str)


def test_filter_contextes():
    from jenkins_epo.repository import Head

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


@patch('jenkins_epo.repository.cached_request')
def test_fetch_combined(cached_request):
    from jenkins_epo.repository import PullRequest

    pr = PullRequest(
        Mock(), payload=dict(number='1', head=dict(ref='x', sha='x'))
    )

    ret = pr.fetch_combined_status()

    assert ret == cached_request.return_value


@patch('jenkins_epo.repository.GITHUB')
def test_delete_branch(GITHUB):
    from jenkins_epo.repository import PullRequest

    GITHUB.dry = False

    pr = PullRequest(Mock(), payload=dict(head=dict(ref='x', sha='x')))
    pr.delete_branch()
    assert GITHUB.repos.mock_calls


@patch('jenkins_epo.repository.GITHUB')
def test_delete_branch_dry(GITHUB):
    from jenkins_epo.repository import PullRequest

    pr = PullRequest(Mock(), payload=dict(head=dict(ref='x', sha='x')))
    pr.delete_branch()
    assert not GITHUB.repos.mock_calls


def test_sort_heads():
    from jenkins_epo.repository import Branch, PullRequest

    master = Branch(Mock(), dict(ref='master', object=dict(sha='d0d0')))
    pr = PullRequest(Mock(), dict(
        head=dict(ref='pr', sha='d0d0'), number=1, html_url='pr',
    ))
    urgent_pr = PullRequest(Mock(), dict(
        head=dict(ref='urgent_pr', sha='d0d0'), number=2, html_url='urgent_pr',
    ))
    urgent_pr.urgent = True

    heads = [master, pr, urgent_pr]

    computed = list(reversed(sorted(heads, key=lambda h: h.sort_key())))
    wanted = [urgent_pr, master, pr]

    assert wanted == computed
