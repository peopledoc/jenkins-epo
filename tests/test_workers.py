import asyncio

from asynctest import CoroutineMock
import pytest


def test_task_priority():
    from jenkins_epo.workers import Task

    assert Task(1) > Task(0)


@pytest.mark.asyncio
@asyncio.coroutine
def test_cycle(SETTINGS, mocker):
    from jenkins_epo.workers import WORKERS, Task, PriorityQueue
    SETTINGS.CONCURRENCY = 2

    class MockTask(Task):
        __call__ = CoroutineMock(side_effect=[None, Exception()])

    WORKERS.queue = PriorityQueue()
    yield from WORKERS.start()
    yield from WORKERS.enqueue(Task(0))
    yield from WORKERS.enqueue(MockTask(0))
    yield from WORKERS.enqueue(MockTask(1))
    yield from WORKERS.queue.join()
    yield from WORKERS.terminate()

    assert 2 == len(MockTask.__call__.mock_calls)


@pytest.mark.asyncio
@asyncio.coroutine
def test_cancel(SETTINGS, mocker):
    from jenkins_epo.workers import (
        WORKERS, PriorityQueue, Task, CancelledError
    )
    SETTINGS.CONCURRENCY = 2

    class MockTask(Task):
        __call__ = CoroutineMock(side_effect=CancelledError())

    WORKERS.queue = PriorityQueue()  # Create queue in current loop
    yield from WORKERS.start()
    yield from WORKERS.enqueue(MockTask(0))
    yield from WORKERS.queue.join()
    yield from WORKERS.terminate()

    assert 1 == len(MockTask.__call__.mock_calls)
