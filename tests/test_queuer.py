import asyncio
from unittest.mock import MagicMock, Mock

from asynctest import CoroutineMock
import pytest


def item(*a, **kw):
    my = MagicMock()
    my.__lt__.return_value = True
    return my


@pytest.mark.asyncio
@asyncio.coroutine
def test_ok():
    from jenkins_epo.compat import PriorityQueue
    from jenkins_epo.queuer import Queuer

    queue = PriorityQueue()
    repo = Mock()
    repo.fetch_protected_branches = CoroutineMock()
    repo.process_protected_branches.return_value = [Mock()]
    repo.fetch_pull_requests = CoroutineMock()
    repo.process_pull_requests.return_value = [Mock(), Mock()]

    queuer = Queuer(queue, Mock(side_effect=item))
    yield from queuer.queue_repositories([repo])

    assert not queue.empty()
    assert 3 == queue.qsize()
