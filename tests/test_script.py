import asyncio
import pytest


def test_logging_sync():
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task in {'main', 'unknown'}


@pytest.mark.asyncio
@asyncio.coroutine
def test_logging_async_unknown():
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task is 'unknown'


@pytest.mark.asyncio
@asyncio.coroutine
def test_logging_async():
    asyncio.Task.current_task().logging_id = 'TEST'
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task is 'TEST'
