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
    from jenkins_ghp.bot import Bot

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


@patch('jenkins_ghp.bot.JENKINS')
@patch('jenkins_ghp.bot.GITHUB')
def test_run_new_job(GITHUB, JENKINS):
    from jenkins_ghp.bot import Bot

    bot = Bot()
    bot.extensions = {}

    pr = Mock()

    new_job = Mock()
    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {'new-job': new_job}
    pr.repository.jobs = []
    pr.list_comments.return_value = []

    bot.run(pr)

    assert JENKINS.create_job.mock_calls


@patch('jenkins_ghp.bot.JENKINS')
@patch('jenkins_ghp.bot.GITHUB')
def test_run_new_job_failed(GITHUB, JENKINS):
    from jenkins_ghp.bot import Bot

    JENKINS.create_job.side_effect = Exception('POUET')

    bot = Bot()
    bot.extensions = {}

    pr = Mock()

    new_job = Mock()
    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {'new-job': new_job}
    pr.repository.jobs = []
    pr.list_comments.return_value = []

    bot.run(pr)

    assert bot.current.errors
    assert JENKINS.create_job.mock_calls


@patch('jenkins_ghp.bot.GITHUB')
def test_run_jenkins_job(GITHUB):
    from jenkins_ghp.bot import Bot

    bot = Bot()
    bot.extensions = {}

    pr = Mock()

    jenkins_job = Mock()
    jenkins_job.name = 'jenkins-job'
    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {}
    pr.repository.jobs = [jenkins_job]
    pr.list_comments.return_value = []

    bot.run(pr)

    assert 'jenkins-job' in bot.current.job_specs


@patch('jenkins_ghp.bot.JENKINS')
@patch('jenkins_ghp.bot.GITHUB')
def test_run_job_existant(GITHUB, JENKINS):
    from jenkins_ghp.bot import Bot

    bot = Bot()
    bot.extensions = {}

    pr = Mock()

    jenkins_job1 = Mock()
    jenkins_job1.name = 'job1'
    jenkins_job1.spec.contains.return_value = True

    yml_job1 = Mock()
    yml_job1.name = 'job1'

    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {'job1': yml_job1}
    pr.repository.jobs = [jenkins_job1]
    pr.list_comments.return_value = []

    bot.run(pr)
    assert not JENKINS.create_job.mock_calls
    assert not JENKINS.update_job.mock_calls


@patch('jenkins_ghp.bot.JENKINS')
@patch('jenkins_ghp.bot.GITHUB')
def test_run_job_disabled(GITHUB, JENKINS):
    from jenkins_ghp.bot import Bot

    bot = Bot()
    bot.extensions = {}

    pr = Mock()

    jenkins_job1 = Mock()
    jenkins_job1.name = 'job1'
    jenkins_job1.is_enabled.return_value = False

    yml_job1 = Mock()
    yml_job1.name = 'job1'

    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {'job1': yml_job1}
    pr.repository.jobs = [jenkins_job1]
    pr.list_comments.return_value = []

    bot.run(pr)
    assert not JENKINS.create_job.mock_calls
    assert not JENKINS.update_job.mock_calls
    assert jenkins_job1.is_enabled.mock_calls
    assert not jenkins_job1.contains.mock_calls


@patch('jenkins_ghp.bot.JENKINS')
@patch('jenkins_ghp.bot.GITHUB')
def test_update_job(GITHUB, JENKINS):
    from jenkins_ghp.bot import Bot

    bot = Bot()
    bot.extensions = {}

    pr = Mock()

    jenkins_job1 = Mock()
    jenkins_job1.name = 'job1'
    jenkins_job1.spec.contains.return_value = False

    yml_job1 = Mock()
    yml_job1.name = 'job1'

    pr.commit = dict(committer=dict(date='2016-08-03T16:47:52Z'))
    pr.repository.list_job_specs.return_value = {'job1': yml_job1}
    pr.repository.jobs = [jenkins_job1]
    pr.list_comments.return_value = []

    bot.run(pr)
    assert not JENKINS.create_job.mock_calls
    assert JENKINS.update_job.mock_calls


@patch('jenkins_ghp.bot.pkg_resources')
@patch('jenkins_ghp.bot.JENKINS')
@patch('jenkins_ghp.bot.GITHUB')
def test_run_extension(GITHUB, JENKINS, pkg_resources):
    from jenkins_ghp.bot import Bot

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
