from mock import Mock


def test_compute_skip_null():
    from jenkins_ghp.bot import Bot, BuilderExtension

    pr = Mock()
    pr.list_instructions.return_value = [
        (0, 0, {'skip': None}),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert bot.settings['skip'] == BuilderExtension.SKIP_ALL


def test_compute_skip():
    from jenkins_ghp.bot import Bot, BuilderExtension

    pr = Mock()
    bot = Bot().workon(pr)

    pr.list_instructions.return_value = [(0, 0, 'skip')]
    bot.process_instructions()
    assert bot.settings['skip'] == BuilderExtension.SKIP_ALL

    pr.list_instructions.return_value = [
        (0, 0, {'skip': None}),
        (0, 0, {'skip': ['this']}),
    ]
    bot.process_instructions()
    assert bot.settings['skip'] == ['this']


def test_compute_rebuild():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot().workon(pr)

    pr.list_instructions.return_value = [('DATE', 0, 'rebuild')]
    bot.process_instructions()
    assert bot.settings['rebuild-failed'] == 'DATE'


def test_compute_help():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot().workon(pr)

    pr.list_instructions.return_value = [(0, 'asker', 'help')]
    bot.process_instructions()
    assert 'asker' in bot.settings['help-mentions']

    pr.list_instructions.return_value = [
        (0, 'asker1', 'help'),
        (0, 'bot', 'help-reset'),
    ]
    bot.process_instructions()
    assert not bot.settings['help-mentions']

    pr.list_instructions.return_value = [
        (0, 'asker1', 'help'),
        (0, 'asker2', 'help'),
    ]
    bot.process_instructions()
    assert 'asker1' in bot.settings['help-mentions']
    assert 'asker2' in bot.settings['help-mentions']

    comment = bot.extensions['help'].generate_comment()
    assert '@asker1' in comment
    assert '@asker2' in comment


def test_skip_re():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, {'skip': ['toto.*', '(?!notthis)']}),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert bot.extensions['builder'].skip('toto-doc')
    assert not bot.extensions['builder'].skip('notthis')


def test_skip_re_wrong():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, {'skip': ['*toto)']}),
    ]

    bot = Bot().workon(pr)
    bot.process_instructions()
    assert not bot.extensions['builder'].skip('toto')
