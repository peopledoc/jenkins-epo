from datetime import datetime, timedelta
from unittest.mock import Mock, patch


@patch('jenkins_epo.extensions.jenkins.SETTINGS')
@patch('jenkins_epo.extensions.jenkins.JENKINS')
@patch('jenkins_epo.extensions.jenkins.GITHUB')
def test_no_yml(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions.jenkins import ApiNotFoundError, CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    GITHUB.fetch_file_contents.side_effect = ApiNotFoundError(
        'url', Mock(), Mock())

    head = ext.current.head
    head.repository.url = 'https://github.com/owner/repo.git'
    head.repository.jobs = []

    ext.run()

    assert GITHUB.fetch_file_contents.mock_calls
    assert not JENKINS.create_job.mock_calls
    assert not JENKINS.update_job.mock_calls


@patch('jenkins_epo.extensions.jenkins.SETTINGS')
@patch('jenkins_epo.extensions.jenkins.JENKINS')
@patch('jenkins_epo.extensions.jenkins.GITHUB')
def test_job_new(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions.jenkins import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current
    ext.current.job_specs = {'new_job': Mock()}
    ext.current.jobs = {}

    res = [x for x in ext.process_job_specs()]
    action, spec = res[0]

    assert JENKINS.create_job == action


@patch('jenkins_epo.extensions.jenkins.SETTINGS')
@patch('jenkins_epo.extensions.jenkins.JENKINS')
@patch('jenkins_epo.extensions.jenkins.GITHUB')
def test_job_uptodate(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions.jenkins import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current
    ext.current.refresh_jobs = None
    ext.current.job_specs = {'new_job': Mock()}
    ext.current.job_specs['new_job'].name = 'new_job'
    ext.current.jobs = {'new_job': Mock()}
    ext.current.jobs['new_job'].spec.contains.return_value = True

    res = [x for x in ext.process_job_specs()]

    assert not res


@patch('jenkins_epo.extensions.jenkins.SETTINGS')
@patch('jenkins_epo.extensions.jenkins.JENKINS')
@patch('jenkins_epo.extensions.jenkins.GITHUB')
def test_job_update(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions.jenkins import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current
    ext.current.refresh_jobs = None
    ext.current.job_specs = {'new_job': Mock(config=dict())}
    ext.current.job_specs['new_job'].name = 'new_job'
    ext.current.jobs = {'new_job': Mock()}
    ext.current.jobs['new_job'].spec.contains.return_value = False

    res = [x for x in ext.process_job_specs()]
    assert res

    action, spec = res[0]

    assert action == JENKINS.update_job


@patch('jenkins_epo.extensions.jenkins.CreateJobsExtension.process_job_specs')
@patch('jenkins_epo.extensions.jenkins.SETTINGS')
@patch('jenkins_epo.extensions.jenkins.JENKINS')
@patch('jenkins_epo.extensions.jenkins.GITHUB')
def test_jenkins_create_success(GITHUB, JENKINS, SETTINGS, process_job_specs):
    from jenkins_epo.extensions.jenkins import CreateJobsExtension, UnknownJob

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current
    ext.current.head.repository.jobs = {}

    GITHUB.fetch_file_contents.return_value = '{new_job: {periodic: true}}'
    JENKINS.get_job.side_effect = UnknownJob('POUET')
    JENKINS.create_job.return_value.name = 'new_job'
    process_job_specs.return_value = [(JENKINS.create_job, Mock())]

    ext.run()

    assert not ext.current.errors.append.mock_calls
    assert JENKINS.create_job.mock_calls
    assert ext.current.jobs['new_job'] == JENKINS.create_job.return_value


@patch('jenkins_epo.extensions.jenkins.CreateJobsExtension.process_job_specs')
@patch('jenkins_epo.extensions.jenkins.SETTINGS')
@patch('jenkins_epo.extensions.jenkins.JENKINS')
@patch('jenkins_epo.extensions.jenkins.GITHUB')
def test_jenkins_fails_existing(GITHUB, JENKINS, SETTINGS, process_job_specs):
    from jenkins_epo.extensions.jenkins import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current
    ext.current.errors = []
    ext.current.head.repository.jobs = {'job': Mock()}

    GITHUB.fetch_file_contents.return_value = '{job: toto}'

    JENKINS.update_job.side_effect = Exception('POUET')

    process_job_specs.return_value = [(JENKINS.update_job, Mock())]

    ext.run()

    assert ext.current.errors
    assert JENKINS.update_job.mock_calls


@patch('jenkins_epo.extensions.jenkins.JENKINS')
def test_refresh_job_outdated(JENKINS):
    from jenkins_epo.extensions.jenkins import CreateJobsExtension
    from jenkins_epo.bot import Instruction

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current
    ext.current.errors = []
    ext.current.refresh_jobs = None
    ext.current.job_specs = {'job': Mock(config={})}
    ext.current.job_specs['job'].name = 'job'
    ext.current.jobs = {'job': Mock(
        updated_at=datetime.now() - timedelta(hours=1),
    )}
    ext.current.jobs['job'].name = 'job'
    ext.current.jobs['job'].spec.contains.return_value = True

    ext.process_instruction(Instruction(
        author='author', name='refresh-jobs', date=datetime.now()
    ))

    assert ext.current.refresh_jobs

    items = list(ext.process_job_specs())
    assert 1 == len(items)
    action, spec = items[0]
    assert JENKINS.update_job == action

    ext.current.jobs['job'].updated_at = datetime.now() + timedelta(hours=1)
    items = list(ext.process_job_specs())
    assert 0 == len(items)
