from unittest.mock import patch


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
