import asyncio
import pytest


def test_logging_sync():
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task is 'main'


@pytest.mark.asyncio
@asyncio.coroutine
def test_logging_async():
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task is not 'main'
