from unittest.mock import patch

import pytest


@pytest.mark.asyncio
def test_check_queue_sleep(mocker):
    sleep = mocker.patch('jenkins_epo.main.asyncio.sleep')
    SETTINGS = mocker.patch('jenkins_epo.main.SETTINGS')
    JENKINS = mocker.patch('jenkins_epo.main.JENKINS')

    from jenkins_epo.main import check_queue

    SETTINGS.ALWAYS_QUEUE = False
    JENKINS.is_queue_empty.return_value = False
    sleep.return_value = []

    yield from check_queue(Mock(queue_empty=False))

    assert sleep.mock_calls


@patch('jenkins_epo.main.procedures')
@patch('jenkins_epo.main.CACHE')
def test_bot_logs(CACHE, procedures):
    from jenkins_epo.main import bot

    procedures.list_repositories.return_value = []

    for io in bot():
        pass

    assert procedures.whoami.mock_calls


@patch('jenkins_epo.main.sys.exit')
@patch('jenkins_epo.main.asyncio')
def test_main(asyncio, exit_):
    from jenkins_epo.main import main

    main(argv=['--help'])
