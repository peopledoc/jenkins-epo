from mock import Mock


def test_compute_skip_null():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (0, 0, {'skip': None}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert bot.settings['skip'] == bot.SKIP_ALL


def test_compute_skip():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot()

    pr.list_instructions.return_value = [(0, 0, 'skip')]
    bot.load_instructions(pr)
    assert bot.settings['skip'] == bot.SKIP_ALL

    pr.list_instructions.return_value = [
        (0, 0, {'skip': None}),
        (0, 0, {'skip': ['this']}),
    ]
    bot.load_instructions(pr)
    assert bot.settings['skip'] == ['this']


def test_compute_rebuild():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot()

    pr.list_instructions.return_value = [('DATE', 0, 'rebuild')]
    bot.load_instructions(pr)
    assert bot.settings['rebuild-failed'] == 'DATE'


def test_compute_help():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    bot = Bot()

    pr.list_instructions.return_value = [(0, 'asker', 'help')]
    bot.load_instructions(pr)
    assert bot.help_ in bot.settings['actions']
    assert 'asker' in bot.settings['help-mentions']

    pr.list_instructions.return_value = [
        (0, 'asker1', 'help'),
        (0, 'bot', 'help-reset'),
    ]
    bot.load_instructions(pr)
    assert bot.help_ not in bot.settings['actions']
    assert not bot.settings['help-mentions']

    pr.list_instructions.return_value = [
        (0, 'asker1', 'help'),
        (0, 'asker2', 'help'),
    ]
    bot.load_instructions(pr)
    assert bot.help_ in bot.settings['actions']
    assert 'asker1' in bot.settings['help-mentions']
    assert 'asker2' in bot.settings['help-mentions']

    bot.help_(pr)


def test_skip_re():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, {'skip': ['toto.*', '(?!notthis)']}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert bot.skip('toto-doc')
    assert not bot.skip('notthis')


def test_skip_re_wrong():
    from jenkins_ghp.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, None, {'skip': ['*toto)']}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert not bot.skip('toto')
