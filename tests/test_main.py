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
        main(argv=['--help'])


def test_main_sync(mocker):
    command = mocker.patch('jenkins_epo.main.bot')
    command.__name__ = 'bot'
    command.__code__ = Mock(co_varnames=(), co_argcount=0)
    command._is_coroutine = None
    from jenkins_epo.main import main

    assert not asyncio.iscoroutinefunction(command)

    main(argv=['bot'])

    assert command.mock_calls


def test_main_async(mocker, event_loop):
    command = mocker.patch('jenkins_epo.main.bot', CoroutineMock())
    command.__name__ = 'bot'
    command.__code__ = Mock(co_varnames=(), co_argcount=0)
    from jenkins_epo.main import main

    main(argv=['bot'], loop=event_loop)

    assert command.mock_calls


def test_main_async_exception(mocker, event_loop):
    command = mocker.patch('jenkins_epo.main.bot', CoroutineMock())
    command.__name__ = 'bot'
    command.__code__ = Mock(co_varnames=(), co_argcount=0)
    command.side_effect = ValueError()
    from jenkins_epo.main import main

    with pytest.raises(ValueError):
        main(argv=['bot'], loop=event_loop)

    assert command.mock_calls
    assert event_loop.is_closed()


@pytest.mark.asyncio
@asyncio.coroutine
def test_bot(mocker, SETTINGS):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.process_head = CoroutineMock()
    procedures.queue_heads = CoroutineMock()
    WORKERS = mocker.patch('jenkins_epo.main.WORKERS')
    WORKERS.start = CoroutineMock()
    WORKERS.terminate = CoroutineMock()

    from jenkins_epo.main import bot, PriorityQueue

    class MockQueue(PriorityQueue):
        @asyncio.coroutine
        def join(self):
            yield from self.get()

    WORKERS.start.return_value = MockQueue()

    @asyncio.coroutine
    def enqueue(queue):
        yield from queue.put(head())

    procedures.queue_heads.side_effect = enqueue

    yield from bot()

    assert procedures.queue_heads.mock_calls
    assert WORKERS.start.mock_calls
    assert WORKERS.terminate.mock_calls


@pytest.mark.asyncio
def test_list_heads(mocker):
    sleep = mocker.patch('jenkins_epo.main.asyncio.sleep', CoroutineMock())

    from jenkins_epo.main import list_heads, PriorityQueue

    queue = PriorityQueue()
    PriorityQueue = mocker.patch('jenkins_epo.main.PriorityQueue')
    PriorityQueue.return_value = queue

    procedures = mocker.patch('jenkins_epo.main.procedures')

    @asyncio.coroutine
    def enqueue(*a):
        yield from queue.put(head())

    sleep.side_effect = enqueue
    procedures.queue_heads = CoroutineMock(side_effect=enqueue)

    yield from list_heads()

    assert PriorityQueue.mock_calls
    assert procedures.queue_heads.mock_calls


def test_list_extensions():
    from jenkins_epo.main import list_extensions

    list_extensions()


@pytest.mark.asyncio
@asyncio.coroutine
def test_process(mocker):
    process_url = mocker.patch(
        'jenkins_epo.main.procedures.process_url', CoroutineMock(),
    )
    from jenkins_epo.main import process

    yield from process('http:///')

    assert process_url.mock_calls
