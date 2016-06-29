from unittest.mock import Mock


def test_compute_skip_unindented():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (0, 0, 'jenkins:\nskip: [toto]\n'),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    skip = [re.pattern for re in bot.current.skip]
    assert ['toto'] == skip


def test_compute_skip_null():
    from jenkins_ghp.bot import Bot
    from jenkins_ghp.extensions import BuilderExtension

    pr = Mock()
    pr.list_instructions.return_value = [
        (0, 0, 'jenkins: {skip: }'),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    skip = [re.pattern for re in bot.current.skip]
    assert skip == list(BuilderExtension.SKIP_ALL)


def test_compute_skip():
    from jenkins_ghp.bot import Bot
    from jenkins_ghp.extensions import BuilderExtension

    pr = Mock()
    bot = Bot().workon(pr)

    pr.list_instructions.return_value = [(0, 0, 'jenkins: skip')]
    bot.process_instructions()
    skip = [re.pattern for re in bot.current.skip]
    assert skip == list(BuilderExtension.SKIP_ALL)

    pr.list_instructions.return_value = [
        (0, 0, 'jenkins: {skip: }'),
        (0, 0, 'jenkins: {skip: [this]}'),
    ]
    bot.process_instructions()
    skip = [re.pattern for re in bot.current.skip]
    assert skip == ['this']


def test_compute_rebuild():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot().workon(pr)

    pr.list_instructions.return_value = [('DATE', 0, 'jenkins: rebuild')]
    bot.process_instructions()
    assert bot.current.rebuild_failed == 'DATE'


def test_compute_help():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot().workon(pr)

    pr.list_instructions.return_value = [(0, 'asker', 'jenkins: help')]
    bot.process_instructions()
    assert 'asker' in bot.current.help_mentions

    pr.list_instructions.return_value = [
        (0, 'asker1', 'jenkins: help'),
        (0, 'bot', 'jenkins: help-reset'),
    ]
    bot.process_instructions()
    assert not bot.current.help_mentions

    pr.list_instructions.return_value = [
        (0, 'asker1', 'jenkins: help'),
        (0, 'asker2', 'jenkins: help'),
    ]
    bot.process_instructions()
    assert 'asker1' in bot.current.help_mentions
    assert 'asker2' in bot.current.help_mentions

    comment = bot.extensions['help'].generate_comment()
    assert '@asker1' in comment
    assert '@asker2' in comment


def test_skip_re():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, """jenkins: {skip: ['toto.*', '(?!notthis)']}"""),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert bot.extensions['builder'].skip('toto-doc')
    assert not bot.extensions['builder'].skip('notthis')


def test_skip_re_wrong():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, '''jenkins: {skip: ['*toto)']}'''),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert not bot.extensions['builder'].skip('toto')


def test_match_mixed():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, """jenkins: {jobs: [-toto*, not*]}"""),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert bot.extensions['builder'].skip('toto-doc')
    assert not bot.extensions['builder'].skip('notthis')


def test_match_negate():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, """jenkins: {jobs: ['*', -skip*]}"""),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()

    assert bot.extensions['builder'].skip('skip')
    assert not bot.extensions['builder'].skip('new')


def test_duration_format():
    from jenkins_ghp.extensions import format_duration

    assert '4.2 sec' == format_duration(4200)
    assert '23 sec' == format_duration(23000)
    assert '5 min 4.2 sec' == format_duration(304200)
    assert '2 h 5 min 4.2 sec' == format_duration(7504200)
