import asyncio

from asynctest import CoroutineMock
import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_ok(SETTINGS, mocker):
    from jenkins_epo.workers import WORKERS
    SETTINGS.CONCURRENCY = 2

    class TestMessage(object):
        __call__ = CoroutineMock(side_effect=[None, Exception()])

        def __lt__(self, other):
            return id(self) < id(other)

    queue = yield from WORKERS.start()
    yield from queue.put(TestMessage())
    yield from queue.put(TestMessage())
    yield from queue.join()
    yield from WORKERS.terminate()

    assert 2 == len(TestMessage.__call__.mock_calls)
