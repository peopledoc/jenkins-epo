from mock import Mock


def test_compute_skip_null():
    from jenkins_ghb.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, {'skip': None}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert bot.settings['skip'] == bot.SKIP_ALL


def test_compute_skip_string():
    from jenkins_ghb.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, 'skip'),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert bot.settings['skip'] == bot.SKIP_ALL


def test_compute_skip_override():
    from jenkins_ghb.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, {'skip': None}),
        (None, {'skip': []}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert bot.settings['skip'] == []


def test_skip_re():
    from jenkins_ghb.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, {'skip': ['toto.*', '(?!notthis)']}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert bot.skip('toto-doc')
    assert not bot.skip('notthis')


def test_skip_re_wrong():
    from jenkins_ghb.bot import Bot

    pr = Mock()
    pr.list_instructions.return_value = [
        (None, {'skip': ['*toto)']}),
    ]

    bot = Bot()
    bot.load_instructions(pr)
    assert not bot.skip('toto')
