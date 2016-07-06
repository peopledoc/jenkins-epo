from datetime import datetime, timedelta
from unittest.mock import Mock


def test_skip_non_pr():
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = object()
    ext.process_lgtm(Mock())


def test_pr_behind_base():
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = Mock()
    ext.process_lgtm(Mock())


def test_deny_non_reviewer():
    from jenkins_ghp.bot import Instruction
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_REVIEWERS = []
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


def test_deny_non_reviewer_processed():
    from jenkins_ghp.bot import Instruction
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_REVIEWERS = []
    ext.current.is_behind = False
    ext.current.commit_date = datetime.now()
    ext.current.lgtm = {}
    ext.current.lgtm_denied = [Instruction(
        author='nonreviewer', name='opm',
    )]

    ext.process_instruction(Instruction(
        author='ghp', name='lgtm-processed',
        date=ext.current.commit_date + timedelta(hours=2),
    ))

    assert not ext.current.lgtm
    assert not ext.current.lgtm_denied


def test_pr_updated():
    from jenkins_ghp.bot import Instruction
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_REVIEWERS = []
    ext.current.is_behind = False
    ext.current.commit_date = commit_date = datetime.now()
    ext.current.lgtm = {}
    ext.current.lgtm_denied = []

    ext.process_instruction(Instruction(
        author='nonreviewer', name='opm',
        date=commit_date - timedelta(hours=1),
    ))

    assert not ext.current.lgtm
    assert not ext.current.lgtm_denied


def test_skip_no_lgtm():
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 1
    ext.current.lgtm = {}
    ext.current.lgtm_denied = []

    ret = ext.check_lgtms()
    assert not ret


def test_skip_missing_lgtm():
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 2
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []

    ret = ext.check_lgtms()
    assert not ret


def test_self_lgtm():
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 1
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.head.author = 'author'

    ret = ext.check_lgtms()
    assert not ret


def test_not_green():
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 1
    ext.current.SETTINGS.GHP_LGTM_AUTHOR = False
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.statuses = {'pending-job': {'state': 'pending'}}

    ret = ext.check_statuses()
    assert not ret


def test_merge_fail():
    from jenkins_ghp.extensions import MergerExtension, ApiError

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 1
    ext.current.SETTINGS.GHP_LGTM_AUTHOR = False
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.merge_failed = None
    ext.current.statuses = {}
    ext.current.head.author = 'author'
    ext.current.head.merge.side_effect = ApiError('url', {}, dict(json=dict(
        message="unmergeable",
    )))

    ios = list(ext.run())
    assert ios
    body = ios[0].body
    assert '@author' in body


def test_merge_already_failed():
    from jenkins_ghp.bot import Instruction
    from jenkins_ghp.extensions import MergerExtension

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
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 0
    ext.current.SETTINGS.GHP_LGTM_AUTHOR = False
    ext.current.statuses = {}
    ext.current.head.author = 'author'

    ios = list(ext.run())
    assert not ios


def test_merge_failed_updated():
    from jenkins_ghp.bot import Instruction
    from jenkins_ghp.extensions import MergerExtension

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
    from jenkins_ghp.extensions import MergerExtension

    ext = MergerExtension('merger', Mock())
    ext.current = Mock()
    ext.current.SETTINGS.GHP_LGTM_QUORUM = 1
    ext.current.SETTINGS.GHP_LGTM_AUTHOR = False
    ext.current.lgtm = {'reviewer': Mock()}
    ext.current.lgtm_denied = []
    ext.current.merge_failed = None
    ext.current.statuses = {}
    ext.current.head.author = 'author'
    ext.current.head.ref = 'branchname'

    ios = list(ext.run())
    assert ext.current.head.merge.mock_calls
    assert ios
    body = ios[0].body
    assert '@reviewer' in body