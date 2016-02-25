import fnmatch
import logging
import re

from github import GitHub

from .settings import SETTINGS


logger = logging.getLogger(__name__)


class LazyGithub(object):
    def __init__(self):
        self._instance = None

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    def load(self):
        if not self._instance:
            self._instance = GitHub(access_token=SETTINGS.GITHUB_TOKEN)


GITHUB = LazyGithub()


class PullRequest(object):
    def __init__(self, pr, project):
        self.pr = pr
        self.project = project

    def __str__(self):
        return self.pr['html_url']


class Project(object):
    remote_re = re.compile(
        r'.*github.com[:/](?P<owner>[\w-]+)/(?P<repository>[\w-]+).*'
    )
    pr_limit = [p for p in SETTINGS.GHIB_LIMIT_PR.split(',') if p]

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

    def list_pull_requests(self):
        logger.info(
            "Querying GitHub for %s/%s PR", self.owner, self.repository,
        )

        pulls = (
            GITHUB.repos(self.owner)(self.repository)
            .pulls.get(per_page=b'100')
        )

        for pr in pulls:
            if self.pr_limit:
                for pattern in self.pr_limit:
                    if fnmatch.fnmatch(pr['html_url'], pattern):
                        break
                else:
                    logger.debug("Skipping %s", pr['html_url'])
                    continue

            yield PullRequest(pr, project=self)
