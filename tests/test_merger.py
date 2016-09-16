from datetime import datetime, timedelta
from unittest.mock import Mock


def test_skip_non_pr():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = object()
    ext.process_lgtm(Mock())


def test_pr_behind_base():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = Mock()
    ext.process_lgtm(Mock())


def test_deny_non_reviewer():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = []
    ext.current.is_behind = False
    ext.current.commit_date = datetime.now()
    ext.current.lgtm = {}
    ext.current.lgtm_denied = []

    ext.process_instruction(Instruction(
        author='nonreviewer', name='opm',
        date=ext.current.commit_date + timedelta(hours=1),
    ))

    assert not ext.current.lgtm
    assert ext.current.lgtm_denied

    ext.run()

    assert ext.current.head.comment.mock_calls


def test_deny_non_reviewer_processed():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = []
    ext.current.is_behind = False
    ext.current.commit_date = datetime.now()
    ext.current.lgtm = {}
    ext.current.lgtm_denied = [Instruction(
        author='nonreviewer', name='opm',
    )]

    ext.process_instruction(Instruction(
        author='bot', name='lgtm-processed',
        date=ext.current.commit_date + timedelta(hours=2),
    ))

    assert not ext.current.lgtm
    assert not ext.current.lgtm_denied


def test_pr_updated():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = ['reviewer']
    ext.current.is_behind = False
    ext.current.commit_date = commit_date = datetime.now()
    ext.current.lgtm = {}
    ext.current.lgtm_denied = []

    ext.process_instruction(Instruction(
        author='reviewer', name='opm',
        date=commit_date - timedelta(hours=1),
    ))

    assert not ext.current.lgtm
    assert not ext.current.lgtm_denied


def test_accept_lgtm():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.REVIEWERS = ['reviewer']
    ext.current.is_behind = False
    ext.current.commit_date = commit_date = datetime.now()
    ext.current.lgtm = {}
    ext.current.lgtm_denied = []

    ext.process_instruction(Instruction(
        author='reviewer', name='opm',
        date=commit_date + timedelta(hours=1),
    ))

    assert 'reviewer' in ext.current.lgtm
    assert not ext.current.lgtm_denied


def test_skip_no_lgtm():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.LGTM_QUORUM = 1
    ext.current.lgtm = {}
    ext.current.lgtm_denied = []

    ret = ext.check_lgtms()
    assert not ret


def test_skip_missing_lgtm():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.LGTM_QUORUM = 2
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []

    ret = ext.check_lgtms()
    assert not ret


def test_self_lgtm():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.LGTM_QUORUM = 1
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.head.author = 'author'

    ret = ext.check_lgtms()
    assert not ret


def test_not_green():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.LGTM_QUORUM = 1
    ext.current.SETTINGS.LGTM_AUTHOR = False
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.statuses = {'pending-job': {'state': 'pending'}}

    ret = ext.check_statuses()
    assert not ret


def test_merge_fail():
    from jenkins_epo.extensions import MergerExtension, ApiError

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.LGTM_QUORUM = 1
    ext.current.SETTINGS.LGTM_AUTHOR = False
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.merge_failed = None
    ext.current.statuses = {}
    ext.current.head.author = 'author'
    ext.current.head.merge.side_effect = ApiError('url', {}, dict(json=dict(
        message="unmergeable",
    )))

    ext.run()
    assert ext.current.head.comment.mock_calls
    body = ext.current.head.comment.call_args[1]['body']
    assert '@author' in body


def test_merge_already_failed():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.merge_failed = None
    ext.current.commit_date = datetime.now()

    date_failed = ext.current.commit_date + timedelta(hours=1)

    ext.process_instruction(Instruction(
        author='bot', name='merge-failed', date=date_failed,
    ))

    assert ext.current.merge_failed

    ext.current.lgtm = {}
    ext.current.lgtm_denied = []
    ext.current.SETTINGS.LGTM_QUORUM = 0
    ext.current.SETTINGS.LGTM_AUTHOR = False
    ext.current.statuses = {}
    ext.current.head.author = 'author'

    ext.run()
    assert not ext.current.head.merge.mock_calls


def test_merge_failed_updated():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.merge_failed = None
    ext.current.commit_date = datetime.now()

    date_failed = ext.current.commit_date - timedelta(hours=1)

    ext.process_instruction(Instruction(
        author='bot', name='merge-failed', date=date_failed,
    ))

    assert not ext.current.merge_failed


def test_merge_success():
    from jenkins_epo.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.LGTM_QUORUM = 1
    ext.current.SETTINGS.LGTM_AUTHOR = False
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.merge_failed = None
    ext.current.statuses = {}
    ext.current.head.author = 'author'
    ext.current.head.ref = 'branchname'

    ext.run()
    assert ext.current.head.merge.mock_calls
    assert not ext.current.head.comment.mock_calls
