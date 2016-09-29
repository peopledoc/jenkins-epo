from unittest.mock import Mock, patch

import pytest


@pytest.mark.asyncio
def test_check_queue_sleep(mocker):
    sleep = mocker.patch('jenkins_epo.main.asyncio.sleep')
    SETTINGS = mocker.patch('jenkins_epo.main.SETTINGS')
    JENKINS = mocker.patch('jenkins_epo.main.JENKINS')

    from jenkins_epo.main import check_queue

    SETTINGS.ALWAYS_QUEUE = False
    JENKINS.is_queue_empty.return_value = False
    sleep.return_value = []

    yield from check_queue(Mock(queue_empty=False))

    assert sleep.mock_calls


@pytest.mark.asyncio
def test_bot_settings_fail(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    mocker.patch('jenkins_epo.main.CACHE')
    Bot = mocker.patch('jenkins_epo.main.Bot')

    from jenkins_epo.main import bot

    head = Mock()
    head.repository.load_settings.side_effect = ValueError()
    procedures.iter_heads.return_value = [head]

    yield from bot()

    bot = Bot.return_value
    assert not bot.run.mock_calls


@pytest.mark.asyncio
def test_bot_loop_outdated(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    mocker.patch('jenkins_epo.main.CACHE')
    Bot = mocker.patch('jenkins_epo.main.Bot')

    from jenkins_epo.main import bot

    head = Mock(is_outdated=True)
    procedures.iter_heads.return_value = [head]

    yield from bot()

    bot = Bot.return_value
    assert not bot.run.mock_calls
    assert head.fetch_commit.mock_calls
    assert procedures.iter_heads.mock_calls


@pytest.mark.asyncio
def test_bot_loop_restart_loop(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    mocker.patch('jenkins_epo.main.CACHE')
    SETTINGS = mocker.patch('jenkins_epo.main.SETTINGS')
    SETTINGS.LOOP = 1
    Bot = mocker.patch('jenkins_epo.main.Bot')
    check_queue = mocker.patch('jenkins_epo.main.check_queue')

    from jenkins_epo.main import bot, RestartLoop

    check_queue.side_effect = RestartLoop

    head = Mock(is_outdated=False)
    procedures.iter_heads.return_value = [head]

    yield from bot()

    bot = Bot.return_value
    assert not bot.run.mock_calls


@pytest.mark.asyncio
def test_bot_loop_restart_loop_not_looping(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    mocker.patch('jenkins_epo.main.CACHE')
    SETTINGS = mocker.patch('jenkins_epo.main.SETTINGS')
    SETTINGS.LOOP = 0
    Bot = mocker.patch('jenkins_epo.main.Bot')
    check_queue = mocker.patch('jenkins_epo.main.check_queue')

    from jenkins_epo.main import bot, RestartLoop

    check_queue.side_effect = RestartLoop

    head = Mock(is_outdated=False)
    procedures.iter_heads.return_value = [head]

    yield from bot()

    bot = Bot.return_value
    assert bot.run.mock_calls


@pytest.mark.asyncio
def test_bot_run_raises(mocker):
    Bot = mocker.patch('jenkins_epo.main.Bot')
    mocker.patch('jenkins_epo.main.CACHE')
    check_queue = mocker.patch('jenkins_epo.main.check_queue')
    check_queue.return_value = []
    procedures = mocker.patch('jenkins_epo.main.procedures')
    SETTINGS = mocker.patch('jenkins_epo.main.SETTINGS')
    SETTINGS.LOOP = 0

    from jenkins_epo.main import bot

    head = Mock(is_outdated=False)
    procedures.iter_heads.return_value = [head]

    bot_instance = Bot.return_value
    bot_instance.run.side_effect = ValueError('POUET')

    with pytest.raises(ValueError):
        yield from bot()


@pytest.mark.asyncio
def test_bot_run_log_exception(mocker):
    Bot = mocker.patch('jenkins_epo.main.Bot')
    mocker.patch('jenkins_epo.main.CACHE')
    check_queue = mocker.patch('jenkins_epo.main.check_queue')
    check_queue.return_value = []
    procedures = mocker.patch('jenkins_epo.main.procedures')
    SETTINGS = mocker.patch('jenkins_epo.main.SETTINGS')
    SETTINGS.LOOP = 1

    from jenkins_epo.main import bot

    head = Mock(is_outdated=False)
    procedures.iter_heads.return_value = [head]

    bot_instance = Bot.return_value
    bot_instance.run.side_effect = ValueError('POUET')

    yield from bot()

    assert bot_instance.run.mock_calls


@patch('jenkins_epo.main.sys.exit')
@patch('jenkins_epo.main.asyncio')
def test_main(asyncio, exit_):
    from jenkins_epo.main import main

    main(argv=['--help'])


@patch('jenkins_epo.main.procedures')
def test_list_heads(procedures):
    from jenkins_epo.main import list_heads

    procedures.iter_heads.return_value = iter([Mock()])

    list_heads()
