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
def test_fetch_protected_branches(cached_request):
    from jenkins_epo.repository import Repository

    assert Repository('owner', 'name').fetch_protected_branches()


@patch('jenkins_epo.repository.cached_request')
def test_process_protected_branches(cached_request):
    from jenkins_epo.repository import Repository

    repo = Repository('owner', 'name')
    branches = list(repo.process_protected_branches([{
        'name': 'master',
        'commit': {'sha': 'd0d0cafec0041edeadbeef'},
    }]))

    assert 1 == len(branches)
    assert 'refs/heads/master' == branches[0].ref


@patch('jenkins_epo.repository.cached_request')
def test_fetch_pull_requests(cached_request):
    from jenkins_epo.repository import Repository

    assert Repository('owner', 'name').fetch_pull_requests()


def test_process_pulls():
    from jenkins_epo.repository import Repository

    repo = Repository('owner', 'name')
    repo.pr_filter = ['*2']

    heads = list(repo.process_pull_requests([
        dict(
            html_url='https://github.com/owner/repo/pull/2',
            number=2,
            head=dict(ref='feature', sha='d0d0'),
        ),
        dict(
            html_url='https://github.com/owner/repo/pull/3',
            number=3,
            head=dict(ref='hotfix', sha='cafe'),
        ),
    ]))

    assert 1 == len(heads)
    head = heads[0]
    assert 'feature' == head.ref


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


def test_load_settings_already_loaded():
    from jenkins_epo.repository import Repository

    repo = Repository('owner', 'repo1')
    repo.SETTINGS.update({'REVIEWERS': ['bdfl']})
    repo.load_settings()


def test_process_jenkins_yml_settings():
    from jenkins_epo.repository import Repository

    repo = Repository('owner', 'repo1')
    repo.process_settings(
        jenkins_yml=repr(dict(settings=dict(reviewers=['bdfl', 'hacker']))),
    )
    assert ['bdfl', 'hacker'] == repo.SETTINGS.REVIEWERS


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

    master = Branch(Mock(), dict(name='master', commit=dict(sha='d0d0')))
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


@patch('jenkins_epo.repository.cached_request')
def test_branch_fetch_previous_commits(cached_request):
    cached_request.side_effect = [
        dict(parents=[dict(sha='d0d0cafe')]),
        dict()
    ]
    from jenkins_epo.repository import Branch

    head = Branch(Mock(), dict(name='branch', commit=dict(sha='d0d0cafe')))
    assert list(head.fetch_previous_commits())
    assert cached_request.mock_calls


@patch('jenkins_epo.repository.cached_request')
def test_branch_process_commits(cached_request):
    from jenkins_epo.repository import Branch

    head = Branch(Mock(), dict(name='branch', commit=dict(sha='d0d0cafe')))
    items = list(head.process_commits([dict(sha='cafed0d0')]))
    assert 1 == len(items)


@patch('jenkins_epo.repository.cached_request')
def test_pr_fetch_previous_commits(cached_request):
    from jenkins_epo.repository import PullRequest

    head = PullRequest(Mock(), dict(
        head=dict(ref='pr', sha='d0d0cafe', label='owner:pr'),
        base=dict(label='owner:base'),
    ))
    assert head.fetch_previous_commits()
    assert cached_request.mock_calls


@patch('jenkins_epo.repository.cached_request')
def test_pr_process_commits(cached_request):
    from jenkins_epo.repository import PullRequest

    head = PullRequest(Mock(), dict(
        head=dict(ref='pr', sha='d0d0cafe', label='owner:pr'),
        base=dict(label='owner:base'),
    ))
    items = list(head.process_commits(dict(commits=[
        dict(sha='cafed0d0'),
    ])))
    assert 1 == len(items)


@patch('jenkins_epo.repository.Commit.push_status')
def test_process_status(push_status):
    from jenkins_epo.repository import Commit, CommitStatus

    commit = Commit(Mock(), 'd0d0')
    commit.contexts_filter = []
    commit.process_statuses({'statuses': [{
        'context': 'job1',
        'state': 'pending',
        'target_url': 'http://jenkins/job/url',
        'updated_at': '2016-06-27T11:58:31Z',
        'description': 'Queued!',
    }]})

    assert 'job1' in commit.statuses

    push_status.return_value = None

    commit.maybe_update_status(CommitStatus(context='context'))


@patch('jenkins_epo.repository.Commit.push_status')
def test_update_status(push_status):
    from jenkins_epo.repository import Commit, CommitStatus

    commit = Commit(Mock(), 'd0d0')
    commit.statuses = {}
    push_status.return_value = {
        'context': 'job',
        'updated_at': '2016-08-30T08:25:56Z',
    }

    commit.maybe_update_status(CommitStatus(context='job', state='success'))

    assert 'job' in commit.statuses


@patch('jenkins_epo.repository.GITHUB')
def test_push_status_dry(GITHUB):
    from datetime import datetime
    from jenkins_epo.repository import Commit, CommitStatus

    GITHUB.dry = 1

    commit = Commit(Mock(), 'd0d0')
    commit.statuses = {}
    status = commit.push_status(CommitStatus(
        context='job', state='success', description='desc',
        updated_at=datetime(2016, 9, 13, 13, 41, 00),
    ))
    assert isinstance(status['updated_at'], str)


@patch('jenkins_epo.repository.GITHUB')
def test_push_status_1000(GITHUB):
    from jenkins_epo.repository import Commit, ApiError

    GITHUB.dry = False
    GITHUB.repos.return_value.statuses.return_value.post.side_effect = (
        ApiError('url', Mock(), dict(json=dict()))
    )
    commit = Commit(Mock(), 'd0d0')
    commit.statuses = {}
    status = commit.push_status({
        'context': 'job', 'description': '', 'state': 'success',
    })
    assert status


def test_filter_contextes():
    from jenkins_epo.repository import Commit, CommitStatus

    rebuild_failed = datetime(2016, 8, 11, 16)

    commit = Commit(Mock(), 'd0d0')
    commit.statuses = {
        'backed': CommitStatus({'state': 'pending', 'description': 'Backed'}),
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

    not_built = list(commit.filter_not_built_contexts(
        [
            'backed', 'errored', 'failed', 'green', 'newfailed', 'notbuilt',
            'queued', 'running', 'skipped',
        ],
        rebuild_failed,
    ))

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
    from jenkins_epo.repository import Commit

    commit = Commit(Mock(), sha='x')

    ret = commit.fetch_combined_status()

    assert ret == cached_request.return_value


def test_commit_status_from_build():
    from jenkins_epo.repository import CommitStatus

    status = CommitStatus(context='job', state='pending')
    build = Mock(_data=dict(duration=5, displayName='job'))

    build.get_status.return_value = None
    new_status = status.from_build(build)

    build.get_status.return_value = 'ABORTED'
    new_status = status.from_build(build)
    assert 'error' == new_status['state']

    build.get_status.return_value = 'SUCCESS'
    new_status = status.from_build(build)
    assert 'success' == new_status['state']

    build.get_status.return_value = 'FAILURE'
    new_status = status.from_build(build)
    assert 'failure' == new_status['state']


@patch('jenkins_epo.repository.cached_request')
def test_commit_date(cached_request):
    from jenkins_epo.repository import Commit

    commit = Commit(Mock(), 'd0d0')
    assert repr(commit)

    cached_request.return_value = {
        'commit': {'author': {'date': '2016-10-11T14:45:00Z'}},
    }
    commit.fetch_payload()

    assert 2016 == commit.date.year


def test_commit_outdated(SETTINGS):
    from jenkins_epo.repository import Commit

    repository = Mock()
    repository.SETTINGS.COMMIT_MAX_WEEKS = 5
    commit = Commit(repository, 'cafed0d0', {'commit': {
        'author': {'date': '2015-10-11T14:45:00Z'},
    }})
    assert commit.is_outdated
