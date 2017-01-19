import asyncio
from unittest.mock import Mock, patch

from asynctest import CoroutineMock
import pytest


@patch('jenkins_epo.main.sys.exit')
@patch('jenkins_epo.main.asyncio')
def test_main(asyncio, exit_):
    from jenkins_epo.main import main

    main(argv=['--help'])


@pytest.mark.asyncio
@asyncio.coroutine
def test_bot(mocker, SETTINGS):
    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.process_head = CoroutineMock()
    procedures.iter_heads.return_value = [Mock()]
    procedures.throttle_github = CoroutineMock()
    procedures.whoami = CoroutineMock()

    from jenkins_epo.main import bot

    yield from bot()

    assert procedures.whoami.mock_calls
    assert procedures.iter_heads.mock_calls
    assert procedures.process_head.mock_calls
    assert procedures.throttle_github.mock_calls


@pytest.mark.asyncio
def test_list_heads(mocker):
    from jenkins_epo.main import list_heads

    procedures = mocker.patch('jenkins_epo.main.procedures')
    procedures.iter_heads.return_value = iter([Mock()])

    yield from list_heads()


def test_list_extensions():
    from jenkins_epo.main import list_extensions

    list_extensions()
