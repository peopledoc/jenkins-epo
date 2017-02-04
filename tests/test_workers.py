import asyncio
from unittest.mock import MagicMock

from asynctest import CoroutineMock
import pytest


def head():
    head = MagicMock(name='HEAD')
    head.__lt__ = lambda a, b: id(a) < id(b)
    return head


@pytest.mark.asyncio
@asyncio.coroutine
def test_ok(SETTINGS, mocker):
    from jenkins_epo.workers import WORKERS
    procedures = mocker.patch('jenkins_epo.workers.procedures')
    procedures.throttle_github = CoroutineMock(name='throttle')

    procedures.process_head = CoroutineMock(
        name='process_head',
        side_effect=[None, Exception('TEST')],
    )
    SETTINGS.CONCURRENCY = 2

    queue = yield from WORKERS.start()
    yield from queue.put(head())
    yield from queue.put(head())
    yield from queue.join()
    yield from WORKERS.terminate()

    assert procedures.throttle_github.mock_calls
    assert 2 == len(procedures.process_head.mock_calls)
