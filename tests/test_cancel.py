from unittest.mock import Mock, patch


@patch('jenkins_epo.extensions.JENKINS')
def test_iter_pending(JENKINS):
    from jenkins_epo.extensions import CancellerExtension

    JENKINS.baseurl = 'https://jenkins.lan/'

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current
    last_commit = Mock()
    old_commit = Mock()
    ext.current.head.process_commits.return_value = [
        last_commit, old_commit,
    ]

    last_commit.process_statuses.return_value = {}
    old_commit.process_statuses.return_value = {
        'backed': {'state': 'pending'},
        'otherci': {'state': 'pending', 'target_url': 'https://other'},
        'success': {
            'state': 'success',
            'target_url': 'https://jenkins.lan/job/success/build/1/',
        },
        'running': {
            'context': 'running',
            'state': 'pending',
            'target_url': 'https://jenkins.lan/job/running/build/1/',
        },
    }

    items = list(ext.iter_pending_status())
    assert 1 == len(items)
    commit, status, head = items[0]
    assert commit == old_commit
    assert 'running' == status['context']
    assert head is False


@patch('jenkins_epo.extensions.CancellerExtension.iter_pending_status')
@patch('jenkins_epo.extensions.JENKINS')
def test_head_build_running(JENKINS, iter_pending_status):
    from jenkins_epo.extensions import CancellerExtension, CommitStatus

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current

    commit = Mock()
    iter_pending_status.return_value = [
        (commit, CommitStatus(context='job', target_url='url'), True),
    ]

    build = JENKINS.get_build_from_url.return_value
    build.get_status.return_value = None

    ext.run()

    assert not build.stop.mock_calls
    assert commit.maybe_update_status.mock_calls


@patch('jenkins_epo.extensions.CancellerExtension.iter_pending_status')
@patch('jenkins_epo.extensions.JENKINS')
def test_old_build_running(JENKINS, iter_pending_status):
    from jenkins_epo.extensions import CancellerExtension, CommitStatus

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current

    commit = Mock()
    iter_pending_status.return_value = [
        (commit, CommitStatus(context='job', target_url='url'), False),
    ]

    build = JENKINS.get_build_from_url.return_value
    build.get_status.return_value = None

    ext.run()

    assert build.stop.mock_calls
    assert commit.maybe_update_status.mock_calls


@patch('jenkins_epo.extensions.CancellerExtension.iter_pending_status')
@patch('jenkins_epo.extensions.JENKINS')
def test_old_build_done(JENKINS, iter_pending_status):
    from jenkins_epo.extensions import CancellerExtension, CommitStatus

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current

    commit = Mock()
    iter_pending_status.return_value = [
        (commit, CommitStatus(context='job', target_url='url'), False),
    ]

    build = JENKINS.get_build_from_url.return_value
    build.is_running.return_value = False
    build.get_status.return_value = 'SUCCESS'
    build._data = dict(duration=4, displayName='job')

    ext.run()

    assert not build.stop.mock_calls
    assert commit.maybe_update_status.mock_calls


@patch('jenkins_epo.extensions.CancellerExtension.iter_pending_status')
@patch('jenkins_epo.extensions.JENKINS')
def test_old_build_lost(JENKINS, iter_pending_status):
    from jenkins_epo.extensions import CancellerExtension, CommitStatus

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current

    commit = Mock()
    iter_pending_status.return_value = [
        (commit, CommitStatus(context='job', target_url='url'), False),
    ]

    JENKINS.get_build_from_url.side_effect = Exception('POUET')

    ext.run()

    assert commit.maybe_update_status.mock_calls
