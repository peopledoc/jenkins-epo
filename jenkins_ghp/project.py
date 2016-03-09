# This file is part of jenkins-ghp
#
# jenkins-ghp is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# jenkins-ghp is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# jenkins-ghp.  If not, see <http://www.gnu.org/licenses/>.

import datetime
import logging
import re

from github import GitHub, ApiError, ApiNotFoundError
import requests

from .settings import SETTINGS
from .utils import match, parse_datetime, retry


logger = logging.getLogger(__name__)


class LazyGithub(object):
    def __init__(self):
        self._instance = None
        self.dry = SETTINGS.GHP_DRY_RUN or SETTINGS.GHP_GITHUB_RO

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    def load(self):
        if not self._instance:
            self._instance = GitHub(access_token=SETTINGS.GITHUB_TOKEN)


GITHUB = LazyGithub()


class Project(object):
    remote_re = re.compile(
        r'.*github.com[:/](?P<owner>[\w-]+)/(?P<repository>[\w-]+).*'
    )
    pr_filter = [p for p in SETTINGS.GHP_PR.split(',') if p]
    _branches_settings = None

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
        return '%s/%s' % (self.owner, self.repository)

    @property
    def url(self):
        return 'https://github.com/%s/%s' % (self.owner, self.repository)

    def branches_settings(self):
        if self._branches_settings is None:
            # Parse GHP_BRANCHES
            Project._branches_settings = {}
            for project in SETTINGS.GHP_BRANCHES.split(' '):
                if not project.strip():
                    continue
                project, branches = project.split(':')
                Project._branches_settings[project] = [
                    'refs/heads/' + b for b in branches.split(',')
                ]
        return self._branches_settings.get(str(self), [])

    @retry(wait_fixed=15000)
    def list_branches(self):
        branches = self.branches_settings()

        if not branches:
            logger.debug("No explicit branches configured for %s", self)
            return []

        logger.debug("Search remote branches matching %s", ', '.join(branches))

        ret = []
        for branch in branches:
            try:
                ref = (
                    GITHUB.repos(self.owner)(self.repository)
                    .git(branch).get()
                )
            except ApiNotFoundError:
                logger.warn("Branch %s not found in %s", branch, self)
                continue

            branch = Branch.from_github_payload(self, ref)
            if branch.is_outdated:
                logger.debug(
                    'Skipping branch %s because older than %s weeks',
                    branch, SETTINGS.GHP_COMMIT_MAX_WEEKS
                )
                continue
            ret.append(branch)
        return ret

    @retry(wait_fixed=15000)
    def list_pull_requests(self):
        logger.debug(
            "Querying GitHub for %s/%s PR", self.owner, self.repository,
        )

        pulls = (
            GITHUB.repos(self.owner)(self.repository)
            .pulls.get(per_page=b'100')
        )

        pulls_o = []
        for data in pulls:
            pr = PullRequest(data, project=self)
            if pr.is_outdated:
                logger.debug(
                    'Skipping PR %s because older than %s weeks',
                    pr, SETTINGS.GHP_COMMIT_MAX_WEEKS
                )
                continue

            if match(data['html_url'], self.pr_filter):
                pulls_o.append(pr)
            else:
                logger.debug("Skipping %s", pr)
        return pulls_o

    def list_contexts(self):
        for job in self.jobs:
            for context in job.list_contexts():
                yield context

    @retry(wait_fixed=15000)
    def report_issue(self, title, body):
        if GITHUB.dry:
            logger.info("Would report issue '%s'", title)
            return {'number': 0}

        logger.info("Reporting issue on %s", self)
        return (
            GITHUB.repos(self.owner)(self.repository)
            .issues.post(
                title=title,
                body=body,
            )
        )


class Head(object):
    contexts_filter = [p for p in SETTINGS.GHP_JOBS.split(',') if p]

    def __init__(self, project, sha, ref):
        self.project = project
        self.sha = sha
        self.ref = ref
        self._statuses_cache = None
        self._commit_cache = None

    @property
    def is_outdated(self):
        if not SETTINGS.GHP_COMMIT_MAX_WEEKS:
            return False

        now = datetime.datetime.utcnow()
        commit = self.get_commit()
        age = now - parse_datetime(commit['author']['date'])
        maxage = datetime.timedelta(weeks=SETTINGS.GHP_COMMIT_MAX_WEEKS)
        return age > maxage

    @retry(wait_fixed=15000)
    def get_commit(self):
        if self._commit_cache is None:
            logger.debug(
                "Fetching commit %s", self.sha[:7]
            )
            url = 'https://api.github.com/repos/%s/%s/commits/%s?access_token=%s' % (  # noqa
                self.project.owner, self.project.repository,
                self.sha, SETTINGS.GITHUB_TOKEN
            )
            response = requests.get(url.encode('utf-8'))
            if 403 == response.status_code:
                # Fake a regular githubpy ApiError. Actually to trigger
                # retry on rate limit.
                raise ApiError(url, {}, dict(json=response.json()))
            elif 200 != response.status_code:
                response.raise_for_status()

            data = response.json()
            if 'commit' not in data:
                raise Exception('No commit data')

            commit = data['commit']
            logger.debug("Got commit for %r", self.sha[:7])
            self._commit_cache = commit

        return self._commit_cache

    def list_comments(self):
        raise NotImplemented

    instruction_re = re.compile(
        '('
        # Case beginning:  jenkins: ... or `jenkins: ...`
        '\A`*jenkins:[^\n]*`*' '|'
        # Case one middle line:  jenkins: ...
        '(?!`)\njenkins:[^\n]*' '|'
        # Case middle line teletype:  `jenkins: ...`
        '\n`+jenkins:[^\n]*`+' '|'
        # Case block code: ```\njenkins:\n  ...```
        '```(?:yaml)?\njenkins:[\s\S]*?\n```'
        ')'
    )

    @retry(wait_fixed=15000)
    def list_instructions(self):
        comments = self.list_comments()
        instructions = []
        for comment in comments:
            if comment['body'] is None:
                continue

            body = comment['body'].replace('\r', '')

            for instruction in self.instruction_re.findall(body):
                instruction = instruction.strip().strip('`')
                if instruction.startswith('yaml\n'):
                    instruction = instruction[4:].strip()

                instructions.append((
                    parse_datetime(comment['updated_at']),
                    comment['user']['login'],
                    instruction,
                ))
        return instructions

    def filter_not_built_contexts(self, contexts, rebuild_failed=None):
        not_built = []
        for context in contexts:
            status = self.get_status_for(context)
            state = status.get('state')
            # Skip failed job, unless rebuild asked and old
            if state in {'error', 'failure'}:
                failure_date = parse_datetime(status['updated_at'])
                if not rebuild_failed:
                    continue
                elif failure_date > rebuild_failed:
                    continue
                else:
                    logger.debug(
                        "Requeue failed context %s younger than %s",
                        context, rebuild_failed.strftime('%Y-%m-%d %H:%M:%S')
                    )
            # Skip `Backed`, `New` and `Queued` jobs
            elif state == 'pending':
                # Jenkins deduplicate jobs in the queue. So it's safe to keep
                # triggering the job in case the queue was flushed.
                if status['description'] not in {'Backed', 'New', 'Queued'}:
                    continue
            # Skip other known states
            elif state:
                continue

            not_built.append(context)

        return not_built

    @retry(wait_fixed=15000)
    def get_statuses(self):
        if self._statuses_cache is None:
            if SETTINGS.GHP_IGNORE_STATUSES:
                logger.debug("Skip GitHub statuses")
                statuses = {}
            else:
                logger.debug(
                    "Fetching statuses for %s", self.sha[:7]
                )
                url = 'https://api.github.com/repos/%s/%s/status/%s?access_token=%s&per_page=100' % (  # noqa
                    self.project.owner, self.project.repository,
                    self.sha, SETTINGS.GITHUB_TOKEN
                )
                response = requests.get(url.encode('utf-8'))
                if 403 == response.status_code:
                    # Fake a regular githubpy ApiError. Actually to trigger
                    # retry on rate limit.
                    raise ApiError(url, {}, dict(json=response.json()))
                elif 200 != response.status_code:
                    response.raise_for_status()
                statuses = {
                    x['context']: x
                    for x in response.json()['statuses']
                    if match(x['context'], self.contexts_filter)
                }
                logger.debug("Got status for %r", sorted(statuses.keys()))
            self._statuses_cache = statuses

        return self._statuses_cache

    def get_status_for(self, context):
        return self.get_statuses().get(context, {})

    @retry(wait_fixed=15000)
    def update_statuses(self, context, state, description, target_url=None):
        current_statuses = self.get_statuses()

        new_status = dict(
            context=context, description=description,
            state=state, target_url=target_url,
        )

        if context in current_statuses:
            current_status = {k: current_statuses[context][k] for k in (
                'context', 'description', 'state', 'target_url')}
            if new_status == current_status:
                return

        if GITHUB.dry:
            return logger.info(
                "Would update status %s to %s/%s", context, state, description,
            )

        try:
            logger.info(
                "Set GitHub status %s to %s/%s", context, state, description,
            )
            new_status = (
                GITHUB.repos(self.project.owner)(self.project.repository)
                .statuses(self.sha).post(**new_status)
            )
            self._statuses_cache[context] = new_status
        except ApiError:
            logger.warn(
                'Hit 1000 status updates on %s', self.sha
            )


class Branch(Head):
    @classmethod
    def from_github_payload(cls, project, data):
        return cls(
            project=project,
            ref=data['ref'],
            sha=data['object']['sha']
            )

    def __str__(self):
        return '%s (%s)' % (self.url, self.sha[:7])

    @property
    def url(self):
        return 'https://github.com/%s/%s/tree/%s' % (
            self.project.owner, self.project.repository,
            self.ref[len('refs/heads/'):],
        )

    @retry(wait_fixed=15000)
    def list_comments(self):
        logger.debug("Queyring comments for instructions")
        return (
            GITHUB.repos(self.project.owner)(self.project.repository)
            .commits(self.sha).comments.get()
        )

    @retry(wait_fixed=15000)
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.project.owner)(self.project.repository)
            .commits(self.sha).comments.post(body=body)
        )


class PullRequest(Head):
    def __init__(self, data, project):
        super(PullRequest, self).__init__(
            project,
            sha=data['head']['sha'],
            ref=data['head']['ref'],
        )
        self.data = data
        self._commit_cache = None

    def __str__(self):
        return '%s (%s)' % (self.data['html_url'], self.ref)

    @retry(wait_fixed=15000)
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.project.owner)(self.project.repository)
            .issues(self.data['number']).comments.post(body=body)
        )

    @retry(wait_fixed=15000)
    def list_comments(self):
        logger.debug("Queyring comments for instructions")
        issue = (
            GITHUB.repos(self.project.owner)(self.project.repository)
            .issues(self.data['number'])
        )
        return [issue.get()] + issue.comments.get()
