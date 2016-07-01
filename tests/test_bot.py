from unittest.mock import Mock, patch


def test_parse():
    from jenkins_ghp.bot import Bot

    updated_at = '2016-06-29T11:20:21Z'
    bot = Bot()
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
    assert 'unix_eof' in haystack


@patch('jenkins_ghp.bot.GITHUB')
def test_io_execution(GITHUB):
    from jenkins_ghp.bot import Bot, Extension

    bot = Bot()

    class TestExtension(Extension):
        success_io = Mock()

        none_io = Mock()
        none_io.run.return_value = None

        raising_io = Mock()
        raising_io.run.side_effect = Exception()

        def run(self):
            res = yield self.success_io
            assert res

            res = yield self.none_io
            assert res is None

            try:
                yield self.raising_io
            except Exception as e:
                assert e is self.raising_io.run.side_effect

    ext = TestExtension('mock', bot)
    bot.extensions = {'mock': ext}

    pr = Mock()
    pr.repository.list_jobs.return_value = []
    pr.list_comments.return_value = []

    bot.run(pr)

    assert TestExtension.success_io.run.mock_calls
    assert TestExtension.none_io.run.mock_calls
    assert TestExtension.raising_io.run.mock_calls
