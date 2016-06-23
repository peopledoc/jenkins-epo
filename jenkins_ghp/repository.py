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

from __future__ import absolute_import

import base64
import datetime
import logging
import os.path
import re

from github import ApiError, ApiNotFoundError
import yaml

from .github import cached_request, GITHUB
from .settings import Settings, SETTINGS
from .utils import match, parse_datetime, retry


logger = logging.getLogger(__name__)


class JobSpec(object):
    def __init__(self, repository, name, data=None):
        if isinstance(data, str):
            data = dict(script=data)
        self.data = data or {}
        self.name = name
        self.repository = repository

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(str(self))


class Repository(object):
    remote_re = re.compile(
        r'.*github.com[:/](?P<owner>[\w-]+)/(?P<name>[\w-]+).*'
    )
    pr_filter = [p for p in str(SETTINGS.GHP_PR).split(',') if p]

    @classmethod
    def from_remote(cls, remote_url):
        match = cls.remote_re.match(remote_url)
        if not match:
            raise ValueError('%r is not github' % (remote_url,))
        return cls(**match.groupdict())

    def __init__(self, owner, name, jobs=None):
        self.owner = owner
        self.name = name
        self.jobs = jobs or []
        self.SETTINGS = {}

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __str__(self):
        return '%s/%s' % (self.owner, self.name)

    def __repr__(self):
        return '%s(%r, %r)' % (
            self.__class__.__name__, self.owner, self.name)

    @property
    def url(self):
        return 'https://github.com/%s' % (self,)

    @retry(wait_fixed=15000)
    def list_watched_branches(self):
        branches = [
            b['name'] for b in cached_request(
                GITHUB.repos(self.owner)(self.name).branches,
                protected='true',
            )
        ]
        logger.debug("Protected branches are %s", branches)

        repositories = filter(None, SETTINGS.GHP_REPOSITORIES.split(' '))
        for entry in repositories:
            entry = entry.strip()
            if ':' in entry:
                repository, env_branches = entry.split(':')
            else:
                repository, env_branches = entry, ''

            if self != repository:
                continue

            env_branches = [b for b in env_branches.split(',') if b]
            if not env_branches:
                continue

            branches = env_branches
            logger.info("Override watched branches %s", branches)
            break

        return ['refs/heads/' + b for b in branches if b]

    @retry(wait_fixed=15000)
    def list_reviewers(self):
        collaborators = cached_request(
            GITHUB.repos(self.owner)(self.name).collaborators
        )
        return [c['login'] for c in collaborators if (
            c['site_admin'] or
            c['permissions']['admin'] or
            c['permissions']['push']
        )]

    def fetch_default_settings(self):
        defaults = {}

        defaults['GHP_BRANCHES'] = self.list_watched_branches()
        defaults['GHP_REVIEWERS'] = self.list_reviewers()

        return defaults

    def fetch_settings(self):
        if self.SETTINGS:
            return

        default_settings = self.fetch_default_settings()

        try:
            settings = self.fetch_file_contents('.github/ghp.yml')
            logger.debug("Loading settings from .github/ghp.yml")
        except ApiNotFoundError:
            settings = '{}'

        data = yaml.load(settings)
        assert hasattr(data, 'items'), "Not yml dict/hash"

        local_settings = {
            'GHP_' + k.upper(): v
            for k, v in data.items()
        }

        all_settings = {}
        all_settings.update(default_settings)
        all_settings.update(SETTINGS)
        all_settings.update(local_settings)

        self.SETTINGS = Settings(**all_settings)
        self.post_process_settings()

    def post_process_settings(self):
        self.SETTINGS.GHP_BRANCHES = [
            b if b.startswith('refs/heads') else 'refs/heads/%s' % b
            for b in self.SETTINGS['GHP_BRANCHES']
        ]

        logger.debug("Repository settings:")
        for k, v in sorted(self.SETTINGS.items()):
            logger.debug("%s=%r", k, v)

    @retry(wait_fixed=15000)
    def fetch_file_contents(self, path, **kwargs):
        # Search file and gets its contents.
        path = os.path.normpath(path)
        items = path.split('/')

        # We walk because to avoid 404, it consumes rate limit. Each walk query
        # is cached.
        search = ''
        for needle in items:
            out = cached_request(
                GITHUB.repos(self.owner)(self.name)
                .contents(search.strip('/')), **kwargs
            )

            if needle == items[-1]:
                type_ = 'file'
            else:
                type_ = 'dir'
            entries = [x['name'] for x in out if x['type'] == type_]

            if needle not in entries:
                logger.debug("%s not found", path)
                raise ApiNotFoundError(path, {}, {})
            search += '/' + needle

        payload = cached_request(
            GITHUB.repos(self.owner)(self.name)
            .contents(path)
        )

        return base64.b64decode(payload['content']).decode('utf-8')

    @retry(wait_fixed=15000)
    def list_branches(self):
        branches = self.SETTINGS.GHP_BRANCHES

        if not branches:
            logger.debug("No explicit branches configured for %s", self)
            return []

        logger.debug("Search remote branches matching %s", ', '.join(branches))

        ret = []
        for branch in branches:
            try:
                ref = cached_request(
                    GITHUB.repos(self.owner)(self.name).git(branch)
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
        logger.debug("Querying GitHub for %s PR", self)

        try:
            pulls = cached_request(
                GITHUB.repos(self.owner)(self.name)
                .pulls, per_page=b'100',
            )
        except Exception:
            logger.exception("Failed to list PR for %s", self)
            return []

        pulls_o = []
        for data in pulls:
            pr = PullRequest(data, repository=self)
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
        return reversed(sorted(pulls_o, key=PullRequest.sort_key))

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
            GITHUB.repos(self.owner)(self.name)
            .issues.post(
                title=title,
                body=body,
            )
        )


class Head(object):
    contexts_filter = [p for p in SETTINGS.GHP_JOBS.split(',') if p]

    def __init__(self, repository, sha, ref):
        self.repository = repository
        self.sha = sha
        self.ref = ref
        self._status_cache = None

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
        logger.debug("Fetching commit %s", self.sha[:7])
        data = cached_request(
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .commits(self.sha)
        )
        if 'commit' not in data:
            raise Exception('No commit data')

        return data['commit']

    @retry(wait_fixed=15000)
    def list_jobs(self):
        jobs = set()

        for job in self.repository.jobs:
            jobs.add(job)

        try:
            config = self.repository.fetch_file_contents('jenkins.yml')
        except ApiNotFoundError:
            return []

        config = yaml.load(config)
        for name, params in config.items():
            job = JobSpec(self.repository, name, params)
            jobs.add(job)

        return list(jobs)

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
        if SETTINGS.GHP_IGNORE_STATUSES:
            logger.debug("Skip GitHub statuses")
            return {}
        else:
            if self._status_cache is None:
                logger.debug("Fetching statuses for %s", self.sha[:7])
                response = cached_request(
                    GITHUB.repos(self.repository.owner)(self.repository.name)
                    .status(self.sha),
                    per_page=b'100',
                )
                statuses = {
                    x['context']: x
                    for x in response['statuses']
                    if match(x['context'], self.contexts_filter)
                }
                logger.debug("Got status for %r", sorted(statuses.keys()))
                self._status_cache = statuses
            return self._status_cache

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
                GITHUB.repos(self.repository.owner)(self.repository.name)
                .statuses(self.sha).post(**new_status)
            )
        except ApiError:
            logger.warn(
                'Hit 1000 status updates on %s', self.sha
            )


class Branch(Head):
    @classmethod
    def from_github_payload(cls, repository, data):
        return cls(
            repository=repository,
            ref=data['ref'],
            sha=data['object']['sha']
            )

    def __str__(self):
        return '%s (%s)' % (self.url, self.sha[:7])

    @property
    def url(self):
        return 'https://github.com/%s/tree/%s' % (
            self.repository, self.ref[len('refs/heads/'):],
        )

    @retry(wait_fixed=15000)
    def list_comments(self):
        logger.debug("Queyring comments for instructions")
        return cached_request(
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .commits(self.sha).comments
        )

    @retry(wait_fixed=15000)
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .commits(self.sha).comments.post(body=body.strip())
        )


class PullRequest(Head):
    _urgent_re = re.compile(r'^jenkins: *urgent$', re.MULTILINE)

    def __init__(self, data, repository):
        super(PullRequest, self).__init__(
            repository,
            sha=data['head']['sha'],
            ref=data['head']['ref'],
        )
        self.data = data
        body = (data.get('body') or '').replace('\r', '')
        self.urgent = bool(self._urgent_re.search(body))

    def sort_key(self):
        # Return sort data. Higher is more urgent. By defaults, last PR is
        # built first. This avoid building staled PR first. It's the default
        # order of GitHub PR listing.
        return self.urgent, self.data['number']

    def __str__(self):
        return '%s (%s)' % (self.data['html_url'], self.ref)

    __repr__ = __str__

    @property
    def author(self):
        return self.data['user']['login']

    @retry(wait_fixed=15000)
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .issues(self.data['number']).comments.post(body=body)
        )

    @retry(wait_fixed=15000)
    def list_comments(self):
        logger.debug("Queyring comments for instructions")
        issue = (
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .issues(self.data['number'])
        )
        return [self.data] + cached_request(issue.comments)

    @retry(wait_fixed=15000)
    def is_behind(self):
        base = self.data['base']['label']
        head = self.data['head']['label']
        comparison = cached_request(
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .compare('%s...%s' % (base, head))
        )
        return comparison['behind_by']

    @retry(wait_fixed=15000)
    def merge(self, message=None):
        body = {
            'sha': self.data['head']['sha'],
        }

        if GITHUB.dry:
            return logger.info("Would merge %s", body['sha'])

        logger.debug("Trying merge!")
        (
            GITHUB.repos(self.repository.owner)(self.repository.name)
            .pulls(self.data['number']).merge.put(body=body)
        )
