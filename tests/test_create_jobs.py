from unittest.mock import Mock, patch


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.JENKINS')
@patch('jenkins_epo.extensions.GITHUB')
def test_no_yml(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions import ApiNotFoundError, CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    GITHUB.fetch_file_contents.side_effect = ApiNotFoundError(
        'url', Mock(), Mock())

    head = ext.current.head
    head.repository.url = 'https://github.com/owner/repo.git'
    head.repository.list_job_specs.return_value = {}
    head.repository.jobs = []

    ext.run()

    assert head.repository.list_job_specs.mock_calls
    assert not JENKINS.create_job.mock_calls


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.JENKINS')
@patch('jenkins_epo.extensions.GITHUB')
def test_new_job(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    new_job = Mock()

    head = ext.current.head
    head.repository.url = 'https://github.com/owner/repo.git'
    head.repository.list_job_specs.return_value = {'new-job': new_job}
    head.repository.jobs = []

    ext.run()

    assert JENKINS.create_job.mock_calls


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.JENKINS')
@patch('jenkins_epo.extensions.GITHUB')
def test_new_job_failed(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    new_job = Mock()

    head = ext.current.head
    head.repository.url = 'https://github.com/owner/repo.git'
    head.repository.list_job_specs.return_value = {'new-job': new_job}
    head.repository.jobs = []

    JENKINS.create_job.side_effect = Exception('POUET')

    ext.run()

    assert ext.current.errors
    assert JENKINS.create_job.mock_calls


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.GITHUB')
def test_jenkins_defined_job(GITHUB, SETTINGS):
    from jenkins_epo.extensions import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    jenkins_job = Mock()
    jenkins_job.name = 'jenkins-job'
    head = ext.current.head
    head.repository.list_job_specs.return_value = {}
    head.repository.jobs = [jenkins_job]

    ext.run()

    assert 'jenkins-job' in ext.current.job_specs


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.JENKINS')
@patch('jenkins_epo.extensions.GITHUB')
def test_job_existant(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    jenkins_job1 = Mock()
    jenkins_job1.name = 'job1'
    jenkins_job1.spec.contains.return_value = True

    yml_job1 = Mock()
    yml_job1.name = 'job1'

    pr = ext.current.head
    pr.repository.list_job_specs.return_value = {'job1': yml_job1}
    pr.repository.jobs = [jenkins_job1]

    ext.run()

    assert not JENKINS.create_job.mock_calls
    assert not JENKINS.update_job.mock_calls


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.JENKINS')
@patch('jenkins_epo.extensions.GITHUB')
def test_job_disabled(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    jenkins_job1 = Mock()
    jenkins_job1.name = 'job1'
    jenkins_job1.is_enabled.return_value = False

    yml_job1 = Mock()
    yml_job1.name = 'job1'

    pr = ext.current.head
    pr.repository.list_job_specs.return_value = {'job1': yml_job1}
    pr.repository.jobs = [jenkins_job1]

    ext.run()

    assert not JENKINS.create_job.mock_calls
    assert not JENKINS.update_job.mock_calls
    assert jenkins_job1.is_enabled.mock_calls
    assert not jenkins_job1.contains.mock_calls


@patch('jenkins_epo.extensions.SETTINGS')
@patch('jenkins_epo.extensions.JENKINS')
@patch('jenkins_epo.extensions.GITHUB')
def test_update_job(GITHUB, JENKINS, SETTINGS):
    from jenkins_epo.extensions import CreateJobsExtension

    ext = CreateJobsExtension('createjob', Mock())
    ext.current = ext.bot.current

    jenkins_job1 = Mock()
    jenkins_job1.name = 'job1'
    jenkins_job1.spec.contains.return_value = False

    yml_job1 = Mock()
    yml_job1.name = 'job1'

    pr = ext.current.head
    pr.repository.list_job_specs.return_value = {'job1': yml_job1}
    pr.repository.jobs = [jenkins_job1]
    pr.list_comments.return_value = []

    ext.run()

    assert not JENKINS.create_job.mock_calls
    assert JENKINS.update_job.mock_calls
