from unittest.mock import Mock


def test_pr_urgent():
    from jenkins_epo.repository import PullRequest

    pr1 = PullRequest(payload=dict(
        head=dict(sha='01234567899abcdef', ref='pr1'),
        body=None,
        number=1, html_url='pulls/1',
    ), repository=Mock())
    assert not pr1.urgent
    pr2 = PullRequest(payload=dict(
        head=dict(sha='01234567899abcdef', ref='pr2'),
        body='bla\n\njenkins: urgent',
        number=2, html_url='pulls/2',
    ), repository=Mock())
    assert pr2.urgent
    pr3 = PullRequest(payload=dict(
        head=dict(sha='01234567899abcdef', ref='pr3'),
        body='> jenkins: urgent',
        number=3, html_url='pulls/3',
    ), repository=Mock())
    assert not pr3.urgent
    pr10 = PullRequest(payload=dict(
        head=dict(sha='01234567899abcdef', ref='pr3'),
        body=None,
        number=10, html_url='pulls/10',
    ), repository=Mock())
    assert not pr10.urgent

    github_listing = [pr10, pr3, pr2, pr1]
    build_listing = [pr1, pr3, pr10, pr2]
    assert build_listing == sorted(
        github_listing, key=PullRequest.sort_key
    )
