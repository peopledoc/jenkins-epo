import asyncio
from unittest.mock import Mock

import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_simple(mocker, WORKERS):
    mocker.patch('jenkins_epo.web.WORKERS', WORKERS)
    from jenkins_epo.web import simple_webhook

    req = Mock(GET=dict(head='url://'))
    res = yield from simple_webhook(req)

    assert 200 == res.status
    assert WORKERS.enqueue.mock_calls
