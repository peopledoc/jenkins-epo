from mock import Mock, patch


@patch('jenkins_ghb.project.GITHUB')
def test_parse(GITHUB):
    updated_at = '2016-02-12T16:32:34Z'
    from jenkins_ghb.project import PullRequest

    pr = PullRequest({'number': '123'}, Mock())
    # GITHUB.repos(owner)(repository).issues(id).comments
    issue = GITHUB.repos.return_value.return_value.issues.return_value
    issue.get.return_value = {
        'updated_at': updated_at, 'body': 'jenkins: issue',
        'user': {'login': 'reporter'},
    }
    issue.comments.get.return_value = [
        {
            'body': body,
            'html_url': 'URL' + repr(body),
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
        ]
    ]

    instructions = [i for d, u, i in pr.list_instructions()]

    assert 'issue' in instructions
    assert None not in instructions
    assert '' not in instructions
    assert 'start_line' in instructions
    assert [] not in instructions
    assert ['inline', 'list'] in instructions
    assert dict(empty=[]) in instructions
    assert 'citation' not in instructions
    assert 'hidden' in instructions
    assert dict(key_none=None) in instructions
    assert dict(tick=None) in instructions
    assert dict(ticks_inline=None) in instructions
    assert dict(ticks_one=None) in instructions
    assert dict(indent=[]) in instructions
    assert dict(colored=['toto']) in instructions
    assert 'unix_eof' in instructions
