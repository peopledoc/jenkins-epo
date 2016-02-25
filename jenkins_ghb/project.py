import re


class Project(object):
    remote_re = re.compile(
        r'.*github.com[:/](?P<owner>[\w-]+)/(?P<repository>[\w-]+).*'
    )

    @classmethod
    def from_remote(cls, remote_url):
        match = cls.remote_re.match(remote_url)
        if not match:
            raise ValueError('%r is not github' % (remote_url,))
        return cls(**match.groupdict())

    def __init__(self, owner, repository, jobs=None):
        self.owner = owner
        self.repository = repository
        self.jobs = jobs or []

    def __str__(self):
        return self.url

    @property
    def url(self):
        return 'https://github.com/%s/%s' % (self.owner, self.repository)
