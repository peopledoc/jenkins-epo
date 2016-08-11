from unittest.mock import patch


@patch('jenkins_ghp.main.procedures')
@patch('jenkins_ghp.main.CACHE')
def test_bot_logs(CACHE, procedures):
    from jenkins_ghp.main import bot

    procedures.list_repositories.return_value = []

    for io in bot():
        pass

    assert procedures.whoami.mock_calls
