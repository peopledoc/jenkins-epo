from unittest.mock import Mock


def comment(login='montecristo', **kwargs):
    defaults = dict(
        updated_at='2016-06-29T11:41:47Z',
        body=None,
        user=dict(login=login),
    )
    return dict(defaults, **kwargs)


def test_compute_skip_unindented():
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body='```\njenkins:\nskip: [toto]\n```'),
    ])
    skip = [re.pattern for re in bot.current.skip]
    assert ['toto'] == skip


def test_compute_skip_null():
    from jenkins_ghp.bot import Bot
    from jenkins_ghp.extensions import BuilderExtension

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body='jenkins: {skip: }'),
    ])
    skip = [re.pattern for re in bot.current.skip]
    assert skip == list(BuilderExtension.SKIP_ALL)


def test_compute_skip():
    from jenkins_ghp.bot import Bot
    from jenkins_ghp.extensions import BuilderExtension

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
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([comment(body='jenkins: rebuild')])
    assert bot.current.rebuild_failed


def test_compute_help():
    from jenkins_ghp.bot import Bot

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

    bot.extensions['help'].run()

    man = bot.current.head.comment.call_args[1]['body']
    assert '@asker1' in man
    assert '@asker2' in man


def test_skip_re():
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body="""jenkins: {skip: ['toto.*', '(?!notthis)']}"""),
    ])
    assert bot.extensions['builder'].skip('toto-doc')
    assert not bot.extensions['builder'].skip('notthis')


def test_skip_re_wrong():
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body='''jenkins: {skip: ['*toto)']}'''),
    ])
    assert not bot.extensions['builder'].skip('toto')
    assert bot.current.skip_errors
    bot.extensions['builder'].run()
    assert bot.current.head.comment.mock_calls


def test_match_mixed():
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body="""jenkins: {jobs: [-toto*, not*]}"""),
    ])
    assert bot.extensions['builder'].skip('toto-doc')
    assert not bot.extensions['builder'].skip('notthis')


def test_match_negate():
    from jenkins_ghp.bot import Bot

    bot = Bot().workon(Mock())
    bot.process_instructions([
        comment(body="""jenkins: {jobs: ['*', -skip*]}"""),
    ])

    assert bot.extensions['builder'].skip('skip')
    assert not bot.extensions['builder'].skip('new')


def test_duration_format():
    from jenkins_ghp.extensions import format_duration

    assert '4.2 sec' == format_duration(4200)
    assert '23 sec' == format_duration(23000)
    assert '5 min 4.2 sec' == format_duration(304200)
    assert '2 h 5 min 4.2 sec' == format_duration(7504200)


def test_errors():
    from jenkins_ghp.bot import Bot, Error

    bot = Bot().workon(Mock())
    bot.current.errors = [Error('message', Mock())]

    bot.extensions['error'].run()

    assert bot.current.head.comment.mock_calls


def test_errors_reset():
    from jenkins_ghp.bot import Bot, Error
    from jenkins_ghp.utils import parse_datetime

    bot = Bot().workon(Mock())
    bot.current.errors = [
        Error('message', parse_datetime('2016-08-03T15:58:47Z')),
    ]
    bot.process_instructions([comment(
        body='''jenkins: reset-errors''', updated_at='2016-08-03T17:58:47Z',
    )])

    bot.extensions['error'].run()

    assert not bot.current.head.comment.mock_calls


def test_report():
    from jenkins_ghp.extensions import ReportExtension, Branch

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
