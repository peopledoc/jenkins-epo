import asyncio
from unittest.mock import Mock

from asynctest import CoroutineMock
import pytest


def test_task_priority():
    from jenkins_epo.tasks import ProcessTask, QueuerTask, PrinterTask

    protected_branch = Mock()
    protected_branch.sort_key.return_value = (50,)
    pr = Mock()
    pr.sort_key.return_value = (80,)
    urgent_pr = Mock()
    urgent_pr.sort_key.return_value = (20,)

    assert ProcessTask(protected_branch, Mock()) < ProcessTask(pr, Mock())
    assert ProcessTask(urgent_pr, Mock()) < ProcessTask(pr, Mock())
    assert ProcessTask(pr, Mock(), '20-webhook') < ProcessTask(pr, Mock())

    assert ProcessTask(pr, Mock()) < QueuerTask(Mock(), Mock())
    assert PrinterTask(pr) < QueuerTask(Mock(), Mock())


@pytest.mark.asyncio
@asyncio.coroutine
def test_process():
    from jenkins_epo.tasks import ProcessTask

    pr = Mock(url='url://')
    pr.sort_key.return_value = (80,)

    task = ProcessTask(pr, CoroutineMock())
    assert str(task)

    yield from task()

    assert task.callable_.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_queuer(mocker, WORKERS):
    mocker.patch('jenkins_epo.tasks.WORKERS', WORKERS)
    from jenkins_epo.tasks import QueuerTask

    pr = Mock()
    pr.sort_key.return_value = (80,)

    repo = Mock()
    repo.fetch_protected_branches = CoroutineMock()
    repo.process_protected_branches.return_value = []
    repo.fetch_pull_requests = CoroutineMock()
    repo.process_pull_requests.return_value = [pr]

    task = QueuerTask(repo, Mock())

    yield from task()

    assert str(task)
    assert WORKERS.enqueue.mock_calls
    assert task.task_factory.mock_calls
    assert repo.fetch_protected_branches.mock_calls
    assert repo.fetch_pull_requests.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_printer():
    from jenkins_epo.tasks import PrinterTask

    pr = Mock()
    pr.sort_key.return_value = (80,)

    task = PrinterTask(pr)

    yield from task()

    assert str(task)
