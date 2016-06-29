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

    man = bot.extensions['help'].generate_comment()
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
