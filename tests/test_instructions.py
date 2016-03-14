from mock import Mock, patch


@patch('jenkins_ghp.project.GITHUB')
def test_parse(GITHUB):
    updated_at = '2016-02-12T16:32:34Z'
    from jenkins_ghp.project import PullRequest

    pr = PullRequest(
        {'number': '123', 'head': {'sha': 'c01', 'ref': 'toto'}},
        Mock(),
    )
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
    haystack = '\n\n----\n\n'.join(instructions)

    assert 'issue' in haystack
    assert 'start_line' in haystack
    assert '[inline, list]' in haystack
    assert 'empty' in haystack
    assert 'citation' not in haystack
    assert 'hidden' in haystack
    assert 'key_none' in haystack
    assert 'tick:' in haystack
    assert 'ticks_inline:' in haystack
    assert 'ticks_one:' in haystack
    assert 'indent:' in haystack
    assert 'colored:' in haystack
    assert 'unix_eof' in haystack


def test_pr_urgent():
    from jenkins_ghp.project import PullRequest

    pr1 = PullRequest(data=dict(
        head=dict(sha='01234567899abcdef', ref='pr1'),
        body=None,
        html_url='pulls/1',
    ), project=Mock())
    assert not pr1.urgent
    pr2 = PullRequest(data=dict(
        head=dict(sha='01234567899abcdef', ref='pr2'),
        body='jenkins: urgent',
        html_url='pulls/2',
    ), project=Mock())
    assert pr2.urgent
    pr3 = PullRequest(data=dict(
        head=dict(sha='01234567899abcdef', ref='pr3'),
        body='> jenkins: urgent',
        html_url='pulls/3',
    ), project=Mock())
    assert not pr3.urgent

    github_listing = [pr3, pr2, pr1]
    build_listing = [pr1, pr3, pr2]
    assert build_listing == sorted(
        github_listing, key=PullRequest.sort_key
    )
