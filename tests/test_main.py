import asyncio
from unittest.mock import Mock

from asynctest import CoroutineMock
import pytest


def test_main():
    from jenkins_epo.main import main

    with pytest.raises(SystemExit):
        main(argv=['--help'])


def test_main_sync(mocker):
    command = mocker.patch('jenkins_epo.main.bot')
    command.__name__ = 'bot'
    command._is_coroutine = None
    from jenkins_epo.main import main

    assert not asyncio.iscoroutinefunction(command)

    main(argv=['bot'])

    assert command.mock_calls


def test_main_async(mocker, event_loop):
    command = mocker.patch('jenkins_epo.main.bot', CoroutineMock())
    command.__name__ = 'bot'
    from jenkins_epo.main import main

    main(argv=['bot'], loop=event_loop)

    assert command.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_bot(mocker, SETTINGS):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.process_head = CoroutineMock()
    procedures.iter_heads.return_value = [Mock()]
    procedures.throttle_github = CoroutineMock()
    procedures.whoami = CoroutineMock()

    from jenkins_epo.main import bot

    yield from bot()

    assert procedures.whoami.mock_calls
    assert procedures.iter_heads.mock_calls
    assert procedures.process_head.mock_calls
    assert procedures.throttle_github.mock_calls


@pytest.mark.asyncio
def test_list_heads(mocker):
    from jenkins_epo.main import list_heads

    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.iter_heads.return_value = iter([Mock()])

    yield from list_heads()


def test_list_extensions():
    from jenkins_epo.main import list_extensions

    list_extensions()
