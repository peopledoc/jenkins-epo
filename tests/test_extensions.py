from unittest.mock import Mock, patch


def comment(login='montecristo', **kwargs):
    defaults = dict(
        updated_at='2016-06-29T11:41:47Z',
        body=None,
        user=dict(login=login),
    )
    return dict(defaults, **kwargs)


def test_compute_skip_unindented():
    from jenkins_epo.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body='```\njenkins:\nskip: [toto]\n```'),
    ])
    skip = [re.pattern for re in bot.current.skip]
    assert ['toto'] == skip


def test_compute_skip_null():
    from jenkins_epo.bot import Bot
    from jenkins_epo.extensions import BuilderExtension

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body='jenkins: {skip: }'),
    ])
    skip = [re.pattern for re in bot.current.skip]
    assert skip == list(BuilderExtension.SKIP_ALL)


def test_compute_skip():
    from jenkins_epo.bot import Bot
    from jenkins_epo.extensions import BuilderExtension

    bot = Bot().workon(Mock())

    bot.process_instructions([comment(body='jenkins: skip')])
    skip = [re.pattern for re in bot.current.skip]
    assert skip == list(BuilderExtension.SKIP_ALL)

    bot.process_instructions([
        comment(body='jenkins: {skip: }'),
        comment(body='jenkins: {skip: [this]}'),
    ])
    skip = [re.pattern for re in bot.current.skip]
    assert skip == ['this']


def test_compute_rebuild():
    from jenkins_epo.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([comment(body='jenkins: rebuild')])
    assert bot.current.rebuild_failed


def test_compute_help():
    from jenkins_epo.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(login='asker', body='jenkins: help')
    ])
    assert 'asker' in bot.current.help_mentions

    bot.process_instructions([
        comment(login='asker1', body='jenkins: help'),
        comment(login='bot', body='jenkins: help-reset'),
    ])
    assert not bot.current.help_mentions

    bot.process_instructions([
        comment(login='asker1', body='jenkins: help'),
        comment(login='asker2', body='jenkins: man'),
    ])
    assert 'asker1' in bot.current.help_mentions
    assert 'asker2' in bot.current.help_mentions

    bot.extensions_map['help'].run()

    man = bot.current.head.comment.call_args[1]['body']
    assert '@asker1' in man
    assert '@asker2' in man


def test_skip_re():
    from jenkins_epo.extensions import BuilderExtension
    from jenkins_epo.bot import Instruction

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    ext.current.jobs_match = []
    ext.current.skip = []
    ext.process_instruction(
        Instruction(author='epo', name='skip', args=['toto.*', '(?!notthis)']),
    )
    assert ext.skip('toto-doc')
    assert not ext.skip('notthis')


def test_skip_re_wrong():
    from jenkins_epo.extensions import BuilderExtension
    from jenkins_epo.bot import Instruction

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    ext.current.skip = []
    ext.current.jobs_match = []
    ext.current.job_specs = {}
    ext.current.skip_errors = []
    ext.process_instruction(
        Instruction(author='epo', name='skip', args=['*toto)']),
    )
    assert not ext.skip('toto')
    assert ext.current.skip_errors
    ext.run()
    assert ext.current.head.comment.mock_calls


def test_skip_disabled_job():
    from jenkins_epo.extensions import BuilderExtension

    ext = BuilderExtension('builder', Mock())
    ext.current = ext.bot.current
    job = Mock()
    job.is_enabled.return_value = False
    spec = Mock()
    spec.name = 'job-disabled'
    spec.config = dict()
    ext.current.jobs_match = []
    ext.current.skip = []
    ext.current.skip_errors = []
    ext.current.job_specs = {'job-disabled': spec}
    ext.current.jobs = {'job-disabled': job}
    ext.current.head.ref = 'refs/heads/pr'
    ext.current.last_commit.filter_not_built_contexts.return_value = [
        'job-disabled']
    ext.current.last_commit.maybe_update_status.return_value = {
        'description': 'Disabled',
    }

    ext.run()

    assert not job.build.mock_calls


def test_only_branches():
    from jenkins_epo.extensions import BuilderExtension

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
    ext.current.skip_errors = []

    ext.run()

    assert not job.build.mock_calls

    spec.config = dict(only=['master', 'stable'])

    ext.run()

    assert not job.build.mock_calls


@patch('jenkins_epo.extensions.JENKINS')
def test_build_queue_full(JENKINS):
    from jenkins_epo.extensions import BuilderExtension

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
    ext.current.skip = []
    ext.current.skip_errors = []

    JENKINS.is_queue_empty.return_value = False

    ext.run()

    assert ext.current.last_commit.maybe_update_status.mock_calls
    assert not job.build.mock_calls


@patch('jenkins_epo.extensions.JENKINS')
def test_build_queue_empty(JENKINS):
    from jenkins_epo.extensions import BuilderExtension

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
    ext.current.skip = []
    ext.current.skip_errors = []

    JENKINS.is_queue_empty.return_value = True

    ext.run()

    assert ext.current.last_commit.maybe_update_status.mock_calls
    assert job.build.mock_calls


def test_build_failed():
    from jenkins_epo.extensions import BuilderExtension

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
    ext.current.skip = []
    ext.current.skip_errors = []

    ext.run()

    assert ext.current.last_commit.maybe_update_status.mock_calls
    assert job.build.mock_calls


def test_builder_ignore_perioddc():
    from jenkins_epo.extensions import BuilderExtension

    ext = BuilderExtension('b', Mock())
    ext.current = ext.bot.current
    ext.current.skip_errors = []
    spec = Mock()
    spec.name = 'job'
    spec.config = dict(periodic=True)

    ext.current.job_specs = {'job': spec}

    ext.run()


def test_match_mixed():
    from jenkins_epo.extensions import BuilderExtension
    from jenkins_epo.bot import Instruction

    ext = BuilderExtension('b', Mock())
    ext.current = ext.bot.current
    ext.current.skip = []
    ext.process_instruction(
        Instruction(author='epo', name='jobs', args=['-toto*', 'not*'])
    )

    assert ext.skip('toto-doc')
    assert not ext.skip('notthis')


def test_match_negate():
    from jenkins_epo.extensions import BuilderExtension
    from jenkins_epo.bot import Instruction

    ext = BuilderExtension('b', Mock())
    ext.current = ext.bot.current
    ext.current.skip = []
    ext.process_instruction(
        Instruction(author='epo', name='jobs', args=['*', '-skip*'])
    )

    assert ext.skip('skip')
    assert not ext.skip('new')


def test_errors():
    from jenkins_epo.bot import Bot, Error

    bot = Bot().workon(Mock())
    bot.current.errors = [Error('message', Mock())]

    bot.extensions_map['error'].run()

    assert bot.current.head.comment.mock_calls


def test_errors_reset():
    from jenkins_epo.bot import Bot, Error
    from jenkins_epo.utils import parse_datetime

    bot = Bot().workon(Mock())
    bot.current.errors = [
        Error('message', parse_datetime('2016-08-03T15:58:47Z')),
    ]
    bot.process_instructions([comment(
        body='''jenkins: reset-errors''', updated_at='2016-08-03T17:58:47Z',
    )])

    bot.extensions_map['error'].run()

    assert not bot.current.head.comment.mock_calls


def test_report():
    from jenkins_epo.extensions import ReportExtension, Branch

    ext = ReportExtension('merger', Mock())
    ext.current = Mock()
    ext.current.head = Mock(spec=Branch)
    ext.current.head.sha = 'c0defada'
    ext.current.head.ref = 'refs/heads/branch'
    ext.current.head.repository = Mock()
    ext.current.head.repository.report_issue.return_value = {
        'number': '1',
    }
    ext.current.report_done = None
    ext.current.statuses = {
        'job1': {
            'state': 'failure',
            'target_url': 'build_url',
        },
    }
    ext.run()

    assert ext.current.head.comment.mock_calls
    assert ext.current.head.repository.report_issue.mock_calls
