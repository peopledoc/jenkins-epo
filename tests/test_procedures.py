from unittest.mock import Mock, patch


@patch('jenkins_epo.procedures.cached_request')
def test_whoami(cached_request):
    from jenkins_epo import procedures

    cached_request.return_value = dict(login='aramis')

    assert 'aramis' == procedures.whoami()


@patch('jenkins_epo.procedures.Repository.from_name')
@patch('jenkins_epo.procedures.SETTINGS')
def test_list_repositories_from_envvar(SETTINGS, from_name):
    from jenkins_epo import procedures

    SETTINGS.REPOSITORIES = "owner/repo1:master owner/repo1"
    repositories = procedures.list_repositories()
    assert 1 == len(list(repositories))


@patch('jenkins_epo.procedures.Repository.from_name')
@patch('jenkins_epo.procedures.SETTINGS')
def test_list_repositories_from_envvar_404(SETTINGS, from_name):
    from jenkins_epo import procedures

    SETTINGS.REPOSITORIES = "owner/repo1:master owner/repo1"
    from_name.side_effect = Exception('404')

    repositories = procedures.list_repositories()

    assert 0 == len(list(repositories))


@patch('jenkins_epo.procedures.Repository.from_name')
@patch('jenkins_epo.procedures.SETTINGS')
def test_list_repositories_with_settings(SETTINGS, from_name):
    from jenkins_epo import procedures

    from_name.side_effect = reps = [Mock(), Mock()]
    reps[0].__str__ = lambda x: 'owner/repo1'
    reps[1].__str__ = lambda x: 'owner/repo2'

    SETTINGS.REPOSITORIES = "owner/repo1:master,stable owner/repo2"
    repositories = {
        str(p): p
        for p in procedures.list_repositories(with_settings=True)
    }
    assert 2 == len(list(repositories))
    assert 'owner/repo1' in repositories
    assert reps[0].load_settings.mock_calls
    assert 'owner/repo2' in repositories
    assert reps[1].load_settings.mock_calls


@patch('jenkins_epo.procedures.Repository.from_name')
@patch('jenkins_epo.procedures.SETTINGS')
def test_list_repositories_with_settings_fails(SETTINGS, from_name):
    from jenkins_epo import procedures

    from_name.return_value = repo = Mock()
    repo.__str__ = lambda x: 'owner/repo1'
    repo.load_settings.side_effect = Exception('POUET')

    SETTINGS.REPOSITORIES = "owner/repo1"
    repositories = {
        str(p): p
        for p in procedures.list_repositories(with_settings=True)
    }

    assert 0 == len(list(repositories))
    assert repo.load_settings.mock_calls


@patch('jenkins_epo.procedures.list_repositories')
def test_iter_heads(list_repositories):
    from jenkins_epo.procedures import iter_heads

    a = Mock()
    branch = Mock(token='a/branch')
    branch.sort_key.return_value = False, 100, 'master'
    a.load_branches.return_value = [branch]
    pr = Mock(token='a/pr')
    pr.sort_key.return_value = False, 50, 'feature'
    a.load_pulls.return_value = [pr]
    b = Mock()
    branch = Mock(token='b/branch')
    branch.sort_key.return_value = False, 100, 'master'
    b.load_branches.return_value = [branch]
    pr1 = Mock(token='b/pr1')
    pr1.sort_key.return_value = False, 50, 'feature'
    pr2 = Mock(token='b/pr2')
    pr2.sort_key.return_value = True, 50, 'hotfix'
    b.load_pulls.return_value = [pr1, pr2]

    list_repositories.return_value = [a, b]

    computed = [h.token for h in iter_heads()]
    wanted = ['a/branch', 'b/pr2', 'a/pr', 'b/branch', 'b/pr1']

    assert wanted == computed
