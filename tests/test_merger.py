from datetime import datetime, timedelta
from unittest.mock import Mock


def test_skip_non_pr():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = object()
    ext.process_opm(Mock())


def test_deny_non_reviewer():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = []
    ext.current.commit_date = datetime.now()
    ext.current.opm = {}
    ext.current.opm_denied = []

    ext.process_instruction(Instruction(
        author='nonreviewer', name='opm',
        date=ext.current.commit_date + timedelta(hours=1),
    ))

    assert not ext.current.opm
    assert ext.current.opm_denied

    ext.run()

    assert ext.current.head.comment.mock_calls


def test_deny_outdated_opm():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = ['reviewer']
    ext.current.commit_date = datetime.now()
    ext.current.opm = {}
    ext.current.opm_denied = []

    ext.process_instruction(Instruction(
        author='reviewer', name='opm',
        date=ext.current.commit_date - timedelta(hours=1),
    ))

    assert not ext.current.opm

    ext.run()


def test_deny_non_reviewer_processed():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = []
    ext.current.commit_date = datetime.now()
    ext.current.opm = None
    ext.current.opm_denied = [Instruction(
        author='nonreviewer', name='opm',
    )]

    ext.process_instruction(Instruction(
        author='bot', name='opm-processed',
        date=ext.current.commit_date + timedelta(hours=2),
    ))

    assert not ext.current.opm
    assert not ext.current.opm_denied


def test_accept_lgtm():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = ['reviewer']
    ext.current.commit_date = commit_date = datetime.now()
    ext.current.opm = None
    ext.current.opm_denied = []

    ext.process_instruction(Instruction(
        author='reviewer', name='opm',
        date=commit_date + timedelta(hours=1),
    ))

    assert 'reviewer' == ext.current.opm.author
    assert not ext.current.opm_denied


def test_not_green():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.opm = Mock()
    ext.current.opm_denied = []
    ext.current.head.fetch_combined_status.return_value = {'state': 'error'}

    ext.run()

    assert not ext.current.head.merge.mock_calls


def test_merge_fail():
    from jenkins_epo.extensions import MergerExtension, ApiError

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.opm = Mock(author='reviewer')
    ext.current.opm_denied = []
    ext.current.last_merge_error = None
    ext.current.head.fetch_combined_status.return_value = {'state': 'success'}
    ext.current.head.merge.side_effect = ApiError('url', {}, dict(json=dict(
        message="unmergeable",
    )))

    ext.run()

    assert ext.current.head.comment.mock_calls
    body = ext.current.head.comment.call_args[1]['body']
    assert '@reviewer' in body


def test_merge_already_failed():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension, ApiError

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = ['reviewer']
    ext.current.commit_date = datetime.now()
    ext.current.opm_denied = []

    date_opm = ext.current.commit_date + timedelta(minutes=30)
    date_failed = ext.current.commit_date + timedelta(hours=1)

    ext.process_instruction(Instruction(
        author='reviewer', name='opm', date=date_opm
    ))
    ext.process_instruction(Instruction(
        author='bot', name='last-merge-error', args='error', date=date_failed
    ))

    assert 'error' == ext.current.last_merge_error.args

    ext.current.head.fetch_combined_status.return_value = {'state': 'success'}
    ext.current.head.merge.side_effect = ApiError('url', {}, dict(json=dict(
        message="error",
    )))

    ext.run()

    assert not ext.current.head.comment.mock_calls


def test_merge_success():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.opm = Mock(author='author')
    ext.current.opm_denied = []
    ext.current.last_merge_error = None
    ext.current.head.fetch_combined_status.return_value = {'state': 'success'}

    ext.run()

    assert ext.current.head.merge.mock_calls
    assert not ext.current.head.comment.mock_calls
    assert ext.current.head.delete_branch.mock_calls
