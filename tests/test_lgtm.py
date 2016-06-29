from datetime import datetime, timedelta
from unittest.mock import Mock, patch


def lgtm(updated_at, login='bot', **kwargs):
    defaults = dict(
        updated_at=updated_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        body='jenkins: opm',
        user=dict(login=login),
    )
    return dict(defaults, **kwargs)


def processed(**kwargs):
    return lgtm(login='bot', body='jenkins: lgtm-processed', **kwargs)


def test_skip_no_lgtm():
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([])
    assert not bot.extensions['builder'].check_lgtm()


def test_deny_non_reviewer():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    bot = Bot().workon(Mock())
    bot.current.lgtm_processed = start
    bot.current.head.repository.SETTINGS.GHP_REVIEWERS = ['reviewer']
    bot.process_instructions([
        lgtm(updated_at=start + timedelta(seconds=1), login='nonreviewer'),
    ])
    assert not bot.extensions['builder'].check_lgtm()
    assert bot.current.head.comment.mock_calls


def test_deny_non_reviewer_processed():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.repository.SETTINGS.GHP_REVIEWERS = ['reviewer']

    bot = Bot().workon(pr)
    bot.process_instructions([
        lgtm(updated_at=start + timedelta(hours=1), login='nonreviewer'),
        processed(updated_at=start + timedelta(hours=2)),
    ])
    assert not bot.extensions['builder'].check_lgtm()
    pr.comment.assert_not_called()


def test_skip_updated():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.repository.SETTINGS.GHP_REVIEWERS = ['reviewer']
    pr.repository.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.commit = {'committer': {'date': (
        (start + timedelta(seconds=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions([
        processed(updated_at=start + timedelta(seconds=1)),
        lgtm(updated_at=start + timedelta(seconds=2), login='reviewer'),
    ])
    assert bot.current['lgtm_processed']
    assert not bot.extensions['builder'].check_lgtm()
    assert pr.comment.mock_calls


def test_skip_updated_processed():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.repository.SETTINGS.GHP_REVIEWERS = ['reviewer']
    pr.repository.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.commit = {'committer': {'date': (
        (start + timedelta(seconds=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions([
        processed(updated_at=start + timedelta(seconds=1)),
        lgtm(updated_at=start + timedelta(seconds=2), login='reviewer'),
        processed(updated_at=start + timedelta(seconds=6)),
    ])
    assert bot.current.lgtm_processed
    assert not bot.extensions['builder'].check_lgtm()
    assert not pr.comment.mock_calls


def test_skip_missing_lgtm():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.repository.SETTINGS.GHP_REVIEWERS = ['reviewer1', 'reviewer2']
    pr.repository.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.repository.SETTINGS.GHP_LGTM_QUORUM = 2
    pr.commit = {'committer': {'date': (
        start.strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions([
        processed(updated_at=start + timedelta(seconds=1)),
        lgtm(updated_at=start + timedelta(seconds=2), login='reviewer1'),
    ])
    assert not bot.extensions['builder'].check_lgtm()


def test_skip_dup_lgtm():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.repository.SETTINGS.GHP_REVIEWERS = ['reviewer1', 'reviewer2']
    pr.repository.SETTINGS.GHP_LGTM_AUTHOR = False
    pr.repository.SETTINGS.GHP_LGTM_QUORUM = 2
    pr.commit = {'committer': {'date': (
        start.strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions([
        processed(updated_at=start + timedelta(hours=1)),
        lgtm(updated_at=start + timedelta(hours=2), login='reviewer1'),
        lgtm(updated_at=start + timedelta(hours=3), login='reviewer1'),
    ])
    assert not bot.extensions['builder'].check_lgtm()


def test_self_lgtm():
    from jenkins_ghp.bot import Bot

    start = datetime.now()

    pr = Mock()
    pr.payload = dict(user=dict(login='author'))
    pr.repository.SETTINGS.GHP_REVIEWERS = ['author', 'reviewer']
    pr.repository.SETTINGS.GHP_LGTM_AUTHOR = True
    pr.repository.SETTINGS.GHP_LGTM_QUORUM = 1
    pr.commit = {'committer': {'date': (
        start.strftime('%Y-%m-%dT%H:%M:%SZ')
    )}}

    bot = Bot().workon(pr)
    bot.process_instructions([
        processed(updated_at=start + timedelta(hours=1)),
        lgtm(updated_at=start + timedelta(hours=2), login='reviewer'),
    ])
    assert not bot.extensions['builder'].check_lgtm()


@patch('jenkins_ghp.extensions.BuilderExtension.check_lgtm')
def test_skip_not_green(check_lgtm):
    from jenkins_ghp.bot import Bot, Instruction

    check_lgtm.return_value = [Instruction('lgtm', None, 'reviewer', None)]

    bot = Bot().workon(Mock())
    bot.current.statuses = {'pending-job': {'state': 'pending'}}
    assert not bot.extensions['builder'].check_mergeable()


@patch('jenkins_ghp.extensions.BuilderExtension.check_lgtm')
def test_skip_behind(check_lgtm):
    from jenkins_ghp.bot import Bot, Instruction

    start = datetime.now()

    check_lgtm.return_value = [
        Instruction('lgtm', None, 'reviewer', start + timedelta(hours=4)),
    ]

    pr = Mock()
    pr.author = 'author'
    pr.payload = dict(base=dict(label='forker:fork'))
    pr.is_behind.return_value = 4

    bot = Bot().workon(pr)
    bot.current.lgtm_processed = start
    bot.current.statuses = {'pending-job': {'state': 'success'}}
    assert not bot.extensions['builder'].check_mergeable()
    assert pr.comment.mock_calls


@patch('jenkins_ghp.extensions.BuilderExtension.check_lgtm')
def test_skip_behind_processed(check_lgtm):
    from jenkins_ghp.bot import Bot, Instruction

    start = datetime.now()

    check_lgtm.return_value = [
        Instruction('lgtm', None, 'reviewer', start + timedelta(hours=4)),
    ]

    pr = Mock()
    pr.author = 'author'
    pr.payload = dict(base=dict(label='forker:fork'))
    pr.is_behind.return_value = 4

    bot = Bot().workon(pr)
    bot.current.lgtm_processed = start + timedelta(hours=5)
    bot.current.statuses = {'pending-job': {'state': 'success'}}
    assert not bot.extensions['builder'].check_mergeable()
    assert not pr.comment.mock_calls


@patch('jenkins_ghp.extensions.BuilderExtension.check_mergeable')
def test_merge_fail(check_mergeable):
    from jenkins_ghp.bot import Bot
    from jenkins_ghp.extensions import ApiError

    pr = Mock()
    pr.author = 'author'
    pr.merge.side_effect = ApiError('url', {}, dict(json=dict(
        message="unmergeable",
    )))

    bot = Bot().workon(pr)
    bot.process_instructions([])
    bot.extensions['builder'].maybe_merge()
    assert pr.comment.mock_calls


@patch('jenkins_ghp.extensions.BuilderExtension.check_mergeable')
def test_merge_success(check_mergeable):
    from jenkins_ghp.bot import Bot, Instruction

    check_mergeable.return_value = [
        Instruction('lgtm', None, 'reviewer', None),
    ]

    bot = Bot().workon(Mock())
    bot.process_instructions([])
    bot.extensions['builder'].maybe_merge()
    assert bot.current.head.comment.mock_calls
