import asyncio

from asynctest import CoroutineMock, Mock, patch
import pytest


def test_parse():
    from jenkins_epo.bot import Bot

    updated_at = '2016-06-29T11:20:21Z'
    bot = Bot()
    bot.current = Mock()
    bot.current.errors = []
    instructions = bot.parse_instructions([
        {
            'number': '123',
            'head': {'sha': 'c0cac01a', 'ref': 'toto'},
            'updated_at': updated_at,
            'body': 'jenkins: issue',
            'user': {'login': 'reporter'},
        },
    ] + [{
        'body': body,
        'number': len(body),
        'updated_at': updated_at,
        'user': {'login': 'commenter'},
    } for body in [
        "jenkins:spaceless\n",
        "jenkins:\r\n",
        "jenkins: start_line\r\n",
        "jenkins: []\r\n",
        "jenkins: [inline, list]\r\n",
        "jenkins: {key_none: }\r\n",
        "jenkins: {empty: []}\r\n",
        "> jenkins: citation\r\n",
        """\
<!--\r
jenkins: hidden\r
-->\r
        """,
        """\
Blabla\r
\r
jenkins: middle_line\r
        """,
        "`jenkins: {tick: }`\r\n",
        "```jenkins: {ticks_inline: }```",
        """\
```\r
jenkins: {ticks_one: }\r
```\r
        """,
        """\
```\r
jenkins:\r
  indent: []\r
```\r
        """,
        """\
```yaml\r
jenkins:\r
  colored: [toto]\r
```\r
        """,
        """\
```yml\r
jenkins:\r
  clrd: []\r
```\r
        """,
        '\n``` yaml\njenkins:\n  _colored: []\n```\n',
        """\
```
jenkins: unix_eof
```
        """,
    ]])

    haystack = [i.name for i in instructions]

    assert 'issue' in haystack
    assert 'start_line' in haystack
    assert 'inline' in haystack
    assert 'list' in haystack
    assert 'empty' in haystack
    assert 'citation' not in haystack
    assert 'hidden' in haystack
    assert 'key_none' in haystack
    assert 'tick' in haystack
    assert 'ticks_inline' in haystack
    assert 'ticks_one' in haystack
    assert 'indent' in haystack
    assert 'colored' in haystack
    assert 'clrd' in haystack
    assert '_colored' in haystack
    assert 'unix_eof' in haystack


def test_parse_error():
    from jenkins_epo.bot import Bot

    updated_at = '2016-06-29T11:20:21Z'
    bot = Bot()
    bot.workon(Mock())

    instructions = list(bot.parse_instructions([
        {
            'number': '123',
            'head': {'sha': 'c0cac01a', 'ref': 'toto'},
            'updated_at': updated_at,
            'body': 'jenkins: {skip: skip: }',
            'user': {'login': 'reporter'},
        },
    ]))

    assert not instructions
    assert 1 == len(bot.current.errors)
    error = bot.current.errors[0]
    assert '@reporter' in error.body


@pytest.mark.asyncio
@asyncio.coroutine
def test_extension():
    from jenkins_epo.bot import Extension

    # For the sake of code coverage
    yield from Extension('ext', Mock()).process_job_spec(Mock())


@pytest.mark.asyncio
@asyncio.coroutine
def test_run_extension(mocker):
    pkg_resources = mocker.patch('jenkins_epo.bot.pkg_resources')

    from jenkins_epo.bot import Bot

    ep = Mock()
    ep.name = 'ext'
    pkg_resources.iter_entry_points.return_value = [ep]
    ext = ep.resolve.return_value.return_value
    ext.DEFAULTS = {}
    ext.SETTINGS = {}
    ext.run.return_value = []

    bot = Bot()
    assert 'ext' in bot.extensions_map

    pr = Mock(name='pr', payload=dict())
    pr.fetch_commits = CoroutineMock()
    commits = [Mock()]
    pr.repository.process_commits.return_value = commits
    pr.fetch_comments = CoroutineMock(return_value=[])
    commits[0].fetch_statuses = CoroutineMock()

    yield from bot.run(pr)

    assert pr.fetch_commits.mock_calls
    assert pr.fetch_comments.mock_calls
    assert ext.begin.mock_calls
    assert ext.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_begin_skip_head(mocker):
    pkg_resources = mocker.patch('jenkins_epo.bot.pkg_resources')

    from jenkins_epo.bot import Bot, SkipHead

    ep = Mock()
    ep.name = 'ext'
    pkg_resources.iter_entry_points.return_value = [ep]
    ext = ep.resolve.return_value.return_value
    ext.DEFAULTS = {}
    ext.SETTINGS = {}
    ext.begin.side_effect = SkipHead()

    pr = Mock(name='pr', payload=dict())
    pr.fetch_commits = CoroutineMock()
    commits = [Mock()]
    pr.repository.process_commits.return_value = commits
    pr.fetch_comments = CoroutineMock(return_value=[])
    commits[0].fetch_statuses = CoroutineMock()

    yield from Bot().run(pr)

    assert ext.begin.mock_calls
    assert not ext.run.mock_calls


@pytest.mark.asyncio
@asyncio.coroutine
def test_run_skip_closed(mocker):
    pkg_resources = mocker.patch('jenkins_epo.bot.pkg_resources')

    from jenkins_epo.bot import Bot

    pkg_resources.iter_entry_points.return_value = []
    pr = Mock(name='pr')
    pr.payload = dict(state='closed')

    yield from Bot().run(pr)


@pytest.mark.asyncio
@asyncio.coroutine
def test_run_skip_head(mocker):
    pkg_resources = mocker.patch('jenkins_epo.bot.pkg_resources')

    from jenkins_epo.bot import Bot, SkipHead

    ep = Mock()
    ep.name = 'ext'
    pkg_resources.iter_entry_points.return_value = [ep]
    ext = ep.resolve.return_value.return_value
    ext.DEFAULTS = {}
    ext.SETTINGS = {}
    ext.run.side_effect = SkipHead()

    pr = Mock(name='pr', payload=dict())
    pr.fetch_commits = CoroutineMock()
    commits = [Mock()]
    pr.repository.process_commits.return_value = commits
    pr.fetch_comments = CoroutineMock(return_value=[])
    commits[0].fetch_statuses = CoroutineMock()

    yield from Bot().run(pr)

    assert ext.begin.mock_calls
    assert ext.run.mock_calls


@patch('jenkins_epo.bot.pkg_resources.iter_entry_points')
@patch('jenkins_epo.bot.Bot.ext_patterns', new=[])
def test_filter_extension(iter_entry_points):
    loaded = Mock()
    loaded.name = 'loaded'
    ext = loaded.resolve.return_value.return_value
    ext.SETTINGS = {}
    skipped = Mock()
    skipped.name = 'skipped'

    iter_entry_points.return_value = [loaded, skipped]

    from jenkins_epo.bot import Bot

    Bot.ext_patterns.extend(['*', '-skip*'])

    bot = Bot()

    assert 'loaded' in bot.extensions_map
    assert 'skipped' not in bot.extensions_map


def test_process_instructions():
    from jenkins_epo.bot import Bot

    bot = Bot()
    bot.current = Mock()
    bot.current.SETTINGS.COLLABORATORS = ['collaborator']
    bot.current.denied_instructions = []
    ext = Mock()
    bot.extensions = [ext]

    bot.process_instructions(comments=[
        dict(
            user=dict(login='ghost'),
            body=None,
        ),
        dict(
            user=dict(login='collaborator'),
            updated_at='2017-01-19T15:03:11Z',
            body='jenkins: help',
        ),
        dict(
            user=dict(login='hacker'),
            updated_at='2017-01-19T15:07:11Z',
            body='jenkins: attack',
        ),
    ])

    assert 1 == len(ext.process_instruction.mock_calls)
    assert 1 == len(bot.current.denied_instructions)
