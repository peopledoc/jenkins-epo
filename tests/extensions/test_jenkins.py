from unittest.mock import Mock, patch


def test_compute_rebuild():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.jenkins import BuilderExtension

    ext = BuilderExtension('e', Mock())
    ext.current = ext.bot.current
    ext.process_instruction(
        Instruction(author='author', name='rebuild', date=Mock())
    )
    assert ext.current.rebuild_failed


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_build_queue_full(JENKINS):
    from jenkins_epo.extensions.jenkins import BuilderExtension

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    job = Mock()
    spec = Mock(config=dict())
    spec.name = 'job'
    ext.current.SETTINGS.ALWAYS_QUEUE = False
    ext.current.head.ref = 'refs/heads/pr'
    ext.current.last_commit.filter_not_built_contexts.return_value = ['job']
    ext.current.jobs_match = []
    ext.current.job_specs = {'job': spec}
    ext.current.jobs = {'job': job}
    ext.current.statuses = {}

    JENKINS.is_queue_empty.return_value = False

    ext.run()

    assert ext.current.last_commit.maybe_update_status.mock_calls
    assert not job.build.mock_calls


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_build_queue_empty(JENKINS):
    from jenkins_epo.extensions.jenkins import BuilderExtension

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    job = Mock()
    spec = Mock(config=dict())
    spec.name = 'job'
    ext.current.SETTINGS.ALWAYS_QUEUE = False
    ext.current.head.ref = 'refs/heads/pr'
    ext.current.last_commit.filter_not_built_contexts.return_value = ['job']
    ext.current.last_commit.maybe_update_status.return_value = {
        'description': 'Queued'
    }
    ext.current.jobs_match = []
    ext.current.job_specs = {'job': spec}
    ext.current.jobs = {'job': job}
    ext.current.statuses = {}

    JENKINS.is_queue_empty.return_value = True

    ext.run()

    assert ext.current.last_commit.maybe_update_status.mock_calls
    assert job.build.mock_calls


def test_build_failed():
    from jenkins_epo.extensions.jenkins import BuilderExtension

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    job = Mock()
    job.build.side_effect = Exception('POUET')
    spec = Mock(config=dict())
    spec.name = 'job'
    ext.current.head.ref = 'refs/heads/pr'
    ext.current.last_commit.filter_not_built_contexts.return_value = ['job']
    ext.current.last_commit.maybe_update_status.return_value = {
        'description': 'Queued'
    }
    ext.current.jobs_match = []
    ext.current.job_specs = {'job': spec}
    ext.current.jobs = {'job': job}
    ext.current.statuses = {}

    ext.run()

    assert ext.current.last_commit.maybe_update_status.mock_calls
    assert job.build.mock_calls


def test_builder_ignore_perioddc():
    from jenkins_epo.extensions.jenkins import BuilderExtension

    ext = BuilderExtension('b', Mock())
    ext.current = ext.bot.current
    spec = Mock()
    spec.name = 'job'
    spec.config = dict(periodic=True)

    ext.current.job_specs = {'job': spec}

    ext.run()


def test_only_branches():
    from jenkins_epo.extensions.jenkins import BuilderExtension

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    job = Mock()
    job.is_enabled.return_value = False
    spec = Mock()
    spec.name = 'job'
    spec.config = dict(only='master')
    ext.current.job_specs = {'job': spec}
    ext.current.jobs = {'job': job}
    ext.current.head.filter_not_built_contexts.return_value = ['job']
    ext.current.head.ref = 'refs/heads/pr'

    ext.run()

    assert not job.build.mock_calls

    spec.config = dict(only=['master', 'stable'])

    ext.run()

    assert not job.build.mock_calls


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_cancel_ignore_other(JENKINS):
    from jenkins_epo.extensions.jenkins import CancellerExtension, CommitStatus

    JENKINS.baseurl = 'jenkins://'

    commit = Mock()

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.poll_queue = []
    ext.current.cancel_queue = [
        (commit, CommitStatus(context='ci/...', target_url='circleci://1')),
    ]

    ext.run()

    assert not JENKINS.get_build_from_url.mock_calls
    assert not commit.maybe_update_status.mock_calls


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_cancel_build_running(JENKINS):
    from jenkins_epo.extensions.jenkins import CancellerExtension, CommitStatus

    JENKINS.baseurl = 'jenkins://'

    commit = Mock()

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.poll_queue = []
    ext.current.cancel_queue = [
        (commit, CommitStatus(context='job', target_url='jenkins://job/1')),
    ]
    ext.current.SETTINGS.DRY_RUN = 0

    build = JENKINS.get_build_from_url.return_value
    build.get_status.return_value = None

    ext.run()

    assert build.stop.mock_calls
    assert commit.maybe_update_status.mock_calls


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_poll_build_running(JENKINS):
    from jenkins_epo.extensions.jenkins import CancellerExtension, CommitStatus

    JENKINS.baseurl = 'jenkins://'

    commit = Mock()

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.cancel_queue = []
    ext.current.poll_queue = [
        (commit, CommitStatus(context='job', target_url='jenkins://job/1')),
    ]

    build = JENKINS.get_build_from_url.return_value
    build.get_status.return_value = None

    ext.run()

    assert not build.stop.mock_calls
    assert commit.maybe_update_status.mock_calls


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_poll_lost_build(JENKINS):
    from jenkins_epo.extensions.jenkins import CancellerExtension, CommitStatus

    commit = Mock()

    ext = CancellerExtension('test', Mock())
    ext.current = ext.bot.current
    ext.current.poll_queue = []
    ext.current.cancel_queue = [
        (commit, CommitStatus(context='job', target_url='jenkins://job/1')),
    ]

    JENKINS.baseurl = 'jenkins://'
    JENKINS.get_build_from_url.side_effect = Exception('POUET')

    ext.run()

    assert commit.maybe_update_status.mock_calls
