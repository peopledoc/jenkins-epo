import datetime
import fnmatch
import logging
import re

from github import GitHub, ApiError
import requests
import yaml

from .settings import SETTINGS
from .utils import retry


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
    def __init__(self, data, project):
        self.data = data
        self.project = project
        self._statuses_cache = None

    def __str__(self):
        return self.data['html_url']

    @property
    def ref(self):
        return self.data['head']['ref']

    @retry()
    def get_statuses(self):
        if self._statuses_cache is None:
            if SETTINGS.GHIB_IGNORE_STATUSES:
                logger.debug("Skip GitHub statuses")
                statuses = {}
            else:
                logger.info("Fetching statuses for %s", self)
                url = 'https://api.github.com/repos/%s/%s/status/%s?access_token=%s&per_page=100' % (  # noqa
                    self.project.owner, self.project.repository,
                    self.data['head']['sha'], SETTINGS.GITHUB_TOKEN
                )
                statuses = dict([(x['context'], x) for x in (
                    requests.get(url.encode('utf-8'))
                    .json()['statuses']
                )])
                logger.debug("Got status for %r", sorted(statuses.keys()))
            self._statuses_cache = statuses

        return self._statuses_cache

    def get_status_for(self, context):
        return self.get_statuses()[context]

    instruction_re = re.compile(
        '('
        # Case beginning:  jenkins: XXX or `jenkins: XXX`
        '\A`*jenkins:[^\n\r]*`*' '|'
        # Case one middle line:  jenkins: XXX
        '(?!`)\r\njenkins:[^\n\r]*' '|'
        # Case middle line teletype:  `jenkins: XXX`
        '\r\n`+jenkins:[^\n]*`+' '|'
        # Case block code: ```\njenkins:\n  XXX```
        '```(?:yaml)?\r\njenkins:[^`]*\r\n```'
        ')'
    )

    @retry()
    def list_instructions(self):
        logger.info("Queyring comments for instructions")
        issue = (
            GITHUB.repos(self.project.owner)(self.project.repository)
            .issues(self.data['number'])
        )
        comments = [issue.get()] + issue.comments.get()
        for comment in comments:
            for instruction in self.instruction_re.findall(comment['body']):
                try:
                    instruction = instruction.strip().strip('`')
                    if instruction.startswith('yaml\r\n'):
                        instruction = instruction[6:].strip()
                    instruction = yaml.load(instruction)
                except yaml.error.YAMLError as e:
                    logger.warn(
                        "Invalid YAML instruction in %s", comment['html_url']
                    )
                    logger.debug("%s", e)
                    continue

                if not instruction['jenkins']:
                    # Just skip empty or null instructions.
                    continue

                yield (
                    datetime.datetime.strptime(
                        comment['updated_at'],
                        '%Y-%m-%dT%H:%M:%SZ'
                    ),
                    instruction['jenkins'],
                )

    @retry()
    def update_statuses(self, context, state, description, url=None):
        current_statuses = self.get_statuses()

        new_status = dict(
            context=context, description=description,
            state=state, target_url=url,
        )

        if context in current_statuses:
            current_status = {k: current_statuses[context][k] for k in (
                'context', 'description', 'state', 'target_url')}
            if new_status == current_status:
                return

        try:
            logger.info(
                "Set GitHub status %s to %s/%s", context, state, description,
            )
            new_status = (
                GITHUB.repos(self.project.owner)(self.project.repository)
                .statuses(self.data['head']['sha']).post(**new_status)
            )
            self._statuses_cache[context] = new_status
        except ApiError:
            logger.warn(
                'Hit 1000 status updates on %s', self.data['head']['sha']
            )


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

    @retry()
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

    def list_contextes(self):
        for job in self.jobs:
            for context in job.list_contextes():
                yield context
