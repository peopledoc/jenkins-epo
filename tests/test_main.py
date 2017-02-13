import asyncio
from unittest.mock import MagicMock, Mock

from asynctest import CoroutineMock
import pytest


def head():
    head = MagicMock(name='HEAD')
    head.__lt__ = lambda a, b: id(a) < id(b)
    return head


def test_main():
    from jenkins_epo.main import main

    with pytest.raises(SystemExit):
        main(argv=['inexistant'])


def test_main_sync(mocker):
    COMMANDS = []
    mocker.patch('jenkins_epo.main.COMMANDS', COMMANDS)
    command = Mock()
    command.__name__ = 'bot'
    command.__code__ = Mock(co_varnames=(), co_argcount=0)
    command._is_coroutine = None
    COMMANDS.append(command)
    from jenkins_epo.main import main

    assert not asyncio.iscoroutinefunction(command)

    main(argv=['bot'])

    assert command.mock_calls


def test_main_async(mocker, event_loop):
    COMMANDS = []
    mocker.patch('jenkins_epo.main.COMMANDS', COMMANDS)
    command = CoroutineMock()
    command.__name__ = 'bot'
    command.__code__ = Mock(co_varnames=(), co_argcount=0)
    COMMANDS.append(command)
    from jenkins_epo.main import main

    main(argv=['bot'], loop=event_loop)

    assert command.mock_calls


def test_main_async_exception(mocker, event_loop):
    COMMANDS = []
    mocker.patch('jenkins_epo.main.COMMANDS', COMMANDS)
    command = CoroutineMock()
    command.__name__ = 'bot'
    command.__code__ = Mock(co_varnames=(), co_argcount=0)
    command.side_effect = ValueError()
    COMMANDS.append(command)

    from jenkins_epo.main import main

    with pytest.raises(ValueError):
        main(argv=['bot'], loop=event_loop)

    assert command.mock_calls
    assert event_loop.is_closed()


def test_bot(mocker):
    get_event_loop = mocker.patch('jenkins_epo.main.asyncio.get_event_loop')
    run_app = mocker.patch('jenkins_epo.main.run_app')
    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.poll = CoroutineMock()
    WORKERS = mocker.patch('jenkins_epo.main.WORKERS')
    WORKERS.start = CoroutineMock()

    from jenkins_epo.main import bot

    bot()

    assert get_event_loop.mock_calls
    assert procedures.poll.mock_calls
    assert WORKERS.start.mock_calls
    assert run_app.mock_calls


@pytest.mark.asyncio
def test_list_heads(mocker):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.print_heads = CoroutineMock()
    WORKERS = mocker.patch('jenkins_epo.main.WORKERS')
    WORKERS.start = CoroutineMock()
    WORKERS.terminate = CoroutineMock()

    from jenkins_epo.main import list_heads

    yield from list_heads()

    assert WORKERS.start.mock_calls
    assert procedures.print_heads.mock_calls
    assert WORKERS.terminate.mock_calls


def test_list_extensions():
    from jenkins_epo.main import list_extensions

    list_extensions()


def test_list_plugins():
    from jenkins_epo.main import list_plugins

    list_plugins()


@pytest.mark.asyncio
@asyncio.coroutine
def test_process(mocker):
    whoami = mocker.patch(
        'jenkins_epo.main.procedures.whoami', CoroutineMock(),
    )
    process_url = mocker.patch(
        'jenkins_epo.main.procedures.process_url', CoroutineMock(),
    )
    from jenkins_epo.main import process

    yield from process('http:///')

    assert whoami.mock_calls
    assert process_url.mock_calls
