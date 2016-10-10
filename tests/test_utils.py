from unittest.mock import Mock, patch


def test_match():
    from jenkins_epo.utils import match

    assert match('any', [])

    patterns = [
        '_*',
        '-*skip*',
        '+butthis',
        'andthis',
    ]

    assert match('_my_job', patterns)
    assert not match('other_job', patterns)
    assert not match('_skip', patterns)
    assert match('butthis', patterns)
    assert match('andthis', patterns)

    patterns = [
        '*',
        '-*skip*',
    ]

    assert match('job1', patterns)
    assert match('job2', patterns)
    assert not match('job-skip', patterns)


@patch('jenkins_epo.github.wait_rate_limit_reset')
def test_filter_exception_for_retry(wait_rate_limit_reset):
    from jenkins_epo.utils import (
        filter_exception_for_retry, ApiError, HTTPError,
    )

    assert not filter_exception_for_retry(Exception())
    assert filter_exception_for_retry(IOError())
    e = HTTPError()
    e.response = Mock(status_code=404)
    assert not filter_exception_for_retry(e)
    e.response = Mock(status_code=503)
    assert filter_exception_for_retry(e)

    e = ApiError('url', Mock(), response=dict())
    assert not filter_exception_for_retry(e)

    e = ApiError(
        'url', Mock(),
        response=dict(json=dict(message=('user error'))),
    )
    assert not filter_exception_for_retry(e)

    e = ApiError(
        'url', Mock(),
        response=dict(json=dict(message=('API rate limit exceeded for you'))),
    )
    assert filter_exception_for_retry(e)
    assert wait_rate_limit_reset.mock_calls
    wait_rate_limit_reset.reset_mock()
