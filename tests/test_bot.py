from unittest.mock import Mock, patch


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
  yml: []\r
```\r
        """,
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
    assert 'yml' in haystack
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


@patch('jenkins_epo.bot.pkg_resources')
def test_run_extension(pkg_resources):
    from jenkins_epo.bot import Bot

    ep = Mock()
    ep.name = 'ext'
    pkg_resources.iter_entry_points.return_value = [ep]
    ext = ep.load.return_value.return_value
    ext.DEFAULTS = {}
    ext.SETTINGS = {}

    bot = Bot()
    assert 'ext' in bot.extensions_map

    pr = Mock()
    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {}
    pr.repository.jobs = []
    pr.list_comments.return_value = []

    bot.run(pr)

    assert ext.run.mock_calls
