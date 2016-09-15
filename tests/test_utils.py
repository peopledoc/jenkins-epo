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
