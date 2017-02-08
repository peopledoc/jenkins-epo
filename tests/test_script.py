import asyncio
from unittest.mock import patch
import pytest


def test_systemd_formatter():
    import logging
    from jenkins_epo.script import SystemdFormatter

    logger = logging.getLogger(__name__)
    record = logger.makeRecord(
        name=logger.name, level=logging.DEBUG,
        fn="(unknown file)", lno=0,
        msg="Message", args=(), exc_info=None,
    )
    formatter = SystemdFormatter()
    message = formatter.format(record)
    assert message.startswith('<')


@patch('jenkins_epo.script.os')
def test_logging_verbose(os):
    from jenkins_epo.script import setup_logging

    os.environ = {}
    config = setup_logging()
    assert 'INFO' == config['loggers']['jenkins_epo']['level']
    assert 'info' == config['handlers']['stderr']['formatter']

    os.environ = {'VERBOSE': '1'}
    config = setup_logging()
    assert 'DEBUG' == config['loggers']['jenkins_epo']['level']
    assert 'debug' == config['handlers']['stderr']['formatter']

    os.environ = {'EPO_VERBOSE': '1'}
    config = setup_logging()
    assert 'DEBUG' == config['loggers']['jenkins_epo']['level']
    assert 'debug' == config['handlers']['stderr']['formatter']

    os.environ = {'PYTHONASYNCIODEBUG': '1'}
    config = setup_logging()
    assert 'DEBUG' == config['loggers']['jenkins_epo']['level']
    assert 'adebug' == config['handlers']['stderr']['formatter']


@patch('jenkins_epo.script.os')
def test_logging_systemd(os):
    from jenkins_epo.script import setup_logging

    os.environ = {'SYSTEMD': '1'}
    config = setup_logging()
    assert 'INFO' == config['loggers']['jenkins_epo']['level']
    assert 'systemd' == config['handlers']['stderr']['formatter']


def test_logging_sync():
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task in {'main', 'othr'}


@pytest.mark.asyncio
@asyncio.coroutine
def test_logging_async_unknown():
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task is 'othr'


@pytest.mark.asyncio
@asyncio.coroutine
def test_logging_async():
    asyncio.Task.current_task().logging_id = 'TEST'
    from jenkins_epo.script import AsyncLogRecord

    record = AsyncLogRecord('name', 0, '/pathname', 1, 'message', (), None)
    assert record.task is 'TEST'


def test_entrypoint_success(mocker):
    mocker.patch('jenkins_epo.script.logging')
    from jenkins_epo.script import entrypoint

    mocker.patch('jenkins_epo.main.main')
    CACHE = mocker.patch('jenkins_epo.cache.CACHE')

    with pytest.raises(SystemExit):
        entrypoint()
    assert CACHE.close.mock_calls


def test_entrypoint_interrupt(mocker):
    mocker.patch('jenkins_epo.script.logging')
    from jenkins_epo.script import entrypoint

    main = mocker.patch('jenkins_epo.main.main')
    CACHE = mocker.patch('jenkins_epo.cache.CACHE')

    main.side_effect = KeyboardInterrupt()

    with pytest.raises(SystemExit):
        entrypoint()
    assert CACHE.close.mock_calls


def test_entrypoint_pdb(mocker):
    mocker.patch('jenkins_epo.script.logging')
    from jenkins_epo.script import entrypoint
    from bdb import BdbQuit

    main = mocker.patch('jenkins_epo.main.main')
    CACHE = mocker.patch('jenkins_epo.cache.CACHE')

    main.side_effect = BdbQuit()

    with pytest.raises(SystemExit):
        entrypoint()
    assert CACHE.close.mock_calls
