from unittest.mock import Mock, patch

from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
def test_bot_settings_fail(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    mocker.patch('jenkins_epo.main.CACHE')
    Bot = mocker.patch('jenkins_epo.main.Bot')

    from jenkins_epo.main import bot

    head = Mock()
    head.repository.load_settings.side_effect = ValueError()
    procedures.iter_heads.return_value = [head]

    with pytest.raises(Exception):
        yield from bot()

    bot = Bot.return_value
    assert not bot.run.mock_calls


@pytest.mark.asyncio
def test_bot_settings_denied(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    mocker.patch('jenkins_epo.main.CACHE')
    Bot = mocker.patch('jenkins_epo.main.Bot')

    from jenkins_epo.main import bot, UnauthorizedRepository

    head = Mock()
    head.repository.load_settings.side_effect = UnauthorizedRepository()
    procedures.iter_heads.return_value = [head]

    with pytest.raises(Exception):
        yield from bot()

    bot = Bot.return_value
    assert not bot.run.mock_calls


@pytest.mark.asyncio
def test_bot_run_raises(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.main.Bot')
    mocker.patch('jenkins_epo.main.CACHE')
    procedures = mocker.patch('jenkins_epo.main.procedures')

    from jenkins_epo.main import bot

    head = Mock()
    head.last_commit.is_outdated = False
    procedures.iter_heads.return_value = [head]

    bot_instance = Bot.return_value
    bot_instance.run.side_effect = ValueError('POUET')

    with pytest.raises(Exception):
        yield from bot()


@pytest.mark.asyncio
def test_process_head_log_exception(mocker, SETTINGS):
    Bot = mocker.patch('jenkins_epo.main.Bot')

    from jenkins_epo.main import process_head

    bot = Bot.return_value
    bot.run = CoroutineMock(side_effect=ValueError('POUET'))

    yield from process_head(Mock(sha='cafed0d0'))

    assert bot.run.mock_calls


@patch('jenkins_epo.main.sys.exit')
@patch('jenkins_epo.main.asyncio')
def test_main(asyncio, exit_):
    from jenkins_epo.main import main

    main(argv=['--help'])


@pytest.mark.asyncio
def test_list_heads(mocker):
    from jenkins_epo.main import list_heads

    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.iter_heads.return_value = iter([Mock()])

    yield from list_heads()


def test_list_extensions():
    from jenkins_epo.main import list_extensions

    list_extensions()
