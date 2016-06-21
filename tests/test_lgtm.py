from datetime import datetime, timedelta
from unittest.mock import Mock, patch


def test_skip_no_lgtm():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = []

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert not bot.extensions['builder'].check_lgtm()


def test_deny_non_reviewer():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.project.SETTINGS.GHP_REVIEWERS = ['reviewer']
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = [
        (start + timedelta(seconds=1), 'nonreviewer', 'jenkins: lgtm'),
    ]

    bot = Bot().workon(pr)
    bot.current['lgtm-processed'] = start
    bot.process_instructions()
    assert not bot.extensions['builder'].check_lgtm()
    assert pr.comment.mock_calls


def test_skip_lgtm_processed():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.project.SETTINGS.GHP_REVIEWERS = ['reviewer']
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = [
        (start + timedelta(seconds=1), 'nonreviewer', 'jenkins: lgtm'),
        (start + timedelta(seconds=2), 'bot', 'jenkins: lgtm-processed'),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert not bot.extensions['builder'].check_lgtm()
    pr.comment.assert_not_called()


def test_skip_updated():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.project.SETTINGS.GHP_REVIEWERS = ['reviewer']
    pr.project.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = [
        (start + timedelta(seconds=1), 'bot', 'jenkins: lgtm-processed'),
        (start + timedelta(seconds=2), 'reviewer', 'jenkins: lgtm'),
    ]
    pr.get_commit.return_value = {'committer': {'date': (
        (start + timedelta(seconds=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert bot.current['lgtm-processed']
    assert not bot.extensions['builder'].check_lgtm()
    assert pr.comment.mock_calls


def test_skip_updated_processed():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.project.SETTINGS.GHP_REVIEWERS = ['reviewer']
    pr.project.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = [
        (start + timedelta(seconds=1), 'bot', 'jenkins: lgtm-processed'),
        (start + timedelta(seconds=2), 'reviewer', 'jenkins: lgtm'),
        (start + timedelta(seconds=6), 'bot', 'jenkins: lgtm-processed'),
    ]
    pr.get_commit.return_value = {'committer': {'date': (
        (start + timedelta(seconds=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert bot.current['lgtm-processed']
    assert not bot.extensions['builder'].check_lgtm()
    assert not pr.comment.mock_calls


def test_skip_missing_lgtm():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.project.SETTINGS.GHP_REVIEWERS = ['reviewer1', 'reviewer2']
    pr.project.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.project.SETTINGS.GHP_LGTM_QUORUM = 2
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = [
        (start + timedelta(seconds=1), 'bot', 'jenkins: lgtm-processed'),
        (start + timedelta(seconds=2), 'reviewer1', 'jenkins: lgtm'),
    ]
    pr.get_commit.return_value = {'committer': {'date': (
        start.strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert not bot.extensions['builder'].check_lgtm()


def test_self_lgtm():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.data = dict(user=dict(login='author'))
    pr.project.SETTINGS.GHP_REVIEWERS = ['author', 'reviewer']
    pr.project.SETTINGS.GHP_LGTM_AUTHOR = True
    pr.project.SETTINGS.GHP_LGTM_QUORUM = 1
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = [
        (start + timedelta(seconds=1), 'bot', 'jenkins: lgtm-processed'),
        (start + timedelta(seconds=2), 'reviewer', 'jenkins: lgtm'),
    ]
    pr.get_commit.return_value = {'committer': {'date': (
        start.strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}
    pr.get_statuses.return_value = {'pending-job': {'state': 'success'}}

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert not bot.extensions['builder'].check_lgtm()


@patch('jenkins_ghp.bot.BuilderExtension.check_lgtm')
def test_skip_not_green(check_lgtm):
    from jenkins_ghp.bot import Bot, Instruction

    check_lgtm.return_value = [Instruction('lgtm', None, 'reviewer', None)]

    pr = Mock()
    pr.list_jobs.return_value = []
    pr.get_statuses.return_value = {'pending-job': {'state': 'pending'}}

    bot = Bot().workon(pr)
    assert not bot.extensions['builder'].check_mergeable()


@patch('jenkins_ghp.bot.BuilderExtension.check_lgtm')
def test_skip_behind(check_lgtm):
    from jenkins_ghp.bot import Bot, Instruction

    start = datetime.now()

    check_lgtm.return_value = [
        Instruction('lgtm', None, 'reviewer', start + timedelta(hours=4)),
    ]

    pr = Mock()
    pr.author = 'author'
    pr.data = dict(base=dict(label='forker:fork'))
    pr.get_statuses.return_value = {'pending-job': {'state': 'success'}}
    pr.is_behind.return_value = 4
    pr.list_jobs.return_value = []

    bot = Bot().workon(pr)
    bot.current['lgtm-processed'] = start
    assert not bot.extensions['builder'].check_mergeable()
    assert pr.comment.mock_calls


@patch('jenkins_ghp.bot.BuilderExtension.check_lgtm')
def test_skip_behind_processed(check_lgtm):
    from jenkins_ghp.bot import Bot, Instruction

    start = datetime.now()

    check_lgtm.return_value = [
        Instruction('lgtm', None, 'reviewer', start + timedelta(hours=4)),
    ]

    pr = Mock()
    pr.author = 'author'
    pr.data = dict(base=dict(label='forker:fork'))
    pr.get_statuses.return_value = {'pending-job': {'state': 'success'}}
    pr.is_behind.return_value = 4
    pr.list_jobs.return_value = []

    bot = Bot().workon(pr)
    bot.current['lgtm-processed'] = start + timedelta(hours=5)
    assert not bot.extensions['builder'].check_mergeable()
    assert not pr.comment.mock_calls


@patch('jenkins_ghp.bot.BuilderExtension.check_mergeable')
def test_merge_fail(check_mergeable):
    from jenkins_ghp.bot import Bot, ApiError

    pr = Mock()
    pr.author = 'author'
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = []
    pr.merge.side_effect = ApiError('url', {}, dict(json=dict(
        message="unmergeable",
    )))

    bot = Bot().workon(pr)
    bot.process_instructions()
    bot.extensions['builder'].maybe_merge()
    assert pr.comment.mock_calls


@patch('jenkins_ghp.bot.BuilderExtension.check_mergeable')
def test_merge_success(check_mergeable):
    from jenkins_ghp.bot import Bot, Instruction

    check_mergeable.return_value = [
        Instruction('lgtm', None, 'reviewer', None),
    ]

    pr = Mock()
    pr.list_jobs.return_value = []
    pr.list_instructions.return_value = []

    bot = Bot().workon(pr)
    bot.process_instructions()
    bot.extensions['builder'].maybe_merge()
    assert pr.comment.mock_calls
