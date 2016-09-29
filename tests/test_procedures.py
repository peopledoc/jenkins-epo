from unittest.mock import Mock, patch


@patch('jenkins_epo.procedures.cached_request')
def test_whoami(cached_request):
    from jenkins_epo import procedures

    cached_request.return_value = dict(login='aramis')

    assert 'aramis' == procedures.whoami()


@patch('jenkins_epo.procedures.Repository.from_name')
@patch('jenkins_epo.procedures.SETTINGS')
def test_list_repositories(SETTINGS, from_name):
    from jenkins_epo import procedures

    SETTINGS.REPOSITORIES = "owner/repo1,owner/repo1"
    repositories = procedures.list_repositories()
    assert 1 == len(list(repositories))


@patch('jenkins_epo.procedures.Repository.from_name')
@patch('jenkins_epo.procedures.SETTINGS')
def test_list_repositories_from_envvar_404(SETTINGS, from_name):
    from jenkins_epo import procedures

    SETTINGS.REPOSITORIES = "owner/repo1 owner/repo1"
    from_name.side_effect = Exception('404')

    repositories = procedures.list_repositories()

    assert 0 == len(list(repositories))


@patch('jenkins_epo.procedures.list_repositories')
def test_iter_heads(list_repositories):
    from jenkins_epo.procedures import iter_heads

    a = Mock()
    branch = Mock(token='a/branch')
    branch.sort_key.return_value = False, 100, 'master'
    a.process_protected_branches.return_value = [branch]
    pr = Mock(token='a/pr')
    pr.sort_key.return_value = False, 50, 'feature'
    a.process_pull_requests.return_value = [pr]
    b = Mock()
    branch = Mock(token='b/branch')
    branch.sort_key.return_value = False, 100, 'master'
    b.process_protected_branches.return_value = [branch]
    pr1 = Mock(token='b/pr1')
    pr1.sort_key.return_value = False, 50, 'feature'
    pr2 = Mock(token='b/pr2')
    pr2.sort_key.return_value = True, 50, 'hotfix'
    b.process_pull_requests.return_value = [pr1, pr2]
    c = Mock()
    c.process_protected_branches.return_value = []
    c.process_pull_requests.return_value = []

    list_repositories.return_value = [a, b, c]

    computed = [h.token for h in iter_heads()]
    wanted = ['a/branch', 'b/pr2', 'a/pr', 'b/branch', 'b/pr1']

    assert wanted == computed
