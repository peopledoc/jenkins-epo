import asyncio
from unittest.mock import MagicMock, Mock

from asynctest import CoroutineMock
import pytest


def head():
    head = MagicMock(name='HEAD')
    head.__lt__ = lambda a, b: id(a) < id(b)
    return head


@pytest.mark.asyncio
@asyncio.coroutine
def test_ok():
    from jenkins_epo.compat import PriorityQueue
    from jenkins_epo.queuer import Queuer

    queue = PriorityQueue()
    repo = Mock()
    repo.fetch_protected_branches = CoroutineMock()
    repo.process_protected_branches.return_value = [head()]
    repo.fetch_pull_requests = CoroutineMock()
    repo.process_pull_requests.return_value = [head(), head()]

    queuer = Queuer(queue)
    yield from queuer.queue_repositories([repo])

    assert not queue.empty()
    assert 3 == queue.qsize()
