# This file is part of jenkins-epo
#
# jenkins-epo is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# jenkins-epo is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# jenkins-epo.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

import asyncio
from itertools import islice
from functools import partial
import logging
from urllib.parse import quote as urlquote
import re

from github import ApiError
import yaml

from .github import cached_arequest, unpaginate, GITHUB, ApiNotFoundError
from .settings import SETTINGS
from .utils import Bunch, match, parse_datetime, parse_patterns, retry


logger = logging.getLogger(__name__)


class UnauthorizedRepository(Exception):
    pass


class CommitStatus(dict):
    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        elif isinstance(other, dict):
            known_keys = {'context', 'description', 'state', 'target_url'}
            a = {k: self.get(k) for k in known_keys}
            b = {k: other.get(k) for k in known_keys}
            return a == b
        else:
            raise TypeError("Can't compare with %s.", type(other))

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self['state'])

    def __str__(self):
        return self.get('context', '**UNKNOWN**')

    def __hash__(self):
        return hash(str(self))

    @property
    def is_queueable(self):
        if self.get('state') != 'pending':
            return False
        # Jenkins deduplicate jobs in the queue. So it's safe to keep
        # triggering the job in case the queue was flushed.
        if self.get('description') not in {'Backed', 'New', 'Queued'}:
            return False
        return True

    @property
    def is_running(self):
        if self.is_queueable:
            return False
        if self.get('state') == 'pending':
            return True
        return False

    @property
    def is_skipped(self):
        return (
            self.get('state') == 'success' and
            'Skipped' in self.get('description', '')
        )

    @property
    def is_rebuildable(self):
        if self.get('state') in {'error', 'failure'}:
            return True
        if self.get('description') in {'Skipped', 'Disabled on Jenkins.'}:
            return True
        return False


class RepositoriesRegistry(dict):
    def __init__(self, *a, **kw):
        super(RepositoriesRegistry, self).__init__(*a, **kw)
        self.settings = list(filter(
            None, SETTINGS.REPOSITORIES.replace(' ', ',').split(',')
        ))

    def __contains__(self, item):
        return str(item) in self.settings + list(self.keys())

    def __iter__(self):
        qualnames = list(self.keys())
        if not qualnames:
            qualnames = self.settings
        return iter(qualnames)


REPOSITORIES = RepositoriesRegistry()


class Repository(object):
    heads_filter = parse_patterns(SETTINGS.HEADS)

    @classmethod
    @asyncio.coroutine
    def from_name(cls, owner, name):
        data = yield from cached_arequest(GITHUB.repos(owner)(name))
        return cls(owner=data['owner']['login'], name=data['name'])

    def __init__(self, owner, name, jobs=None):
        self.owner = owner
        self.name = name
        self.jobs = jobs or {}
        self.SETTINGS = Bunch()

    def __str__(self):
        return '%s/%s' % (self.owner, self.name)

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __repr__(self):
        return '%s(%r, %r)' % (
            self.__class__.__name__, self.owner, self.name)

    @property
    def url(self):
        return 'https://github.com/%s' % (self,)

    @asyncio.coroutine
    def fetch_commit(self, sha):
        logger.debug("Querying GitHub for commit %s.", sha[:7])
        payload = yield from cached_arequest(
            GITHUB.repos(self).git.commits(sha)
        )
        return payload

    @asyncio.coroutine
    def fetch_hooks(self):
        payload = yield from cached_arequest(GITHUB.repos(self).hooks)
        return payload

    @asyncio.coroutine
    def fetch_protected_branches(self):
        logger.debug("Querying GitHub for %s protected branches.", self)
        payload = yield from cached_arequest(
            GITHUB.repos(self).branches, protected='true'
        )
        return payload

    @asyncio.coroutine
    def fetch_pull_requests(self):
        logger.debug("Querying GitHub for %s PR.", self)
        payload = yield from cached_arequest(GITHUB.repos(self).pulls)
        return payload

    def process_hooks(self, payload, webhook_url):
        for hook in payload:
            if hook['name'] != 'web':
                continue
            if hook['config']['url'] != webhook_url:
                continue
            yield WebHook(hook)

    def process_protected_branches(self, branches):
        for branch in branches:
            url = '%s/tree/%s' % (self.url, branch['name'])
            if not match(url, self.heads_filter):
                logger.debug("Skipping %s.", url)
            else:
                yield Branch(self, branch)

    def process_pull_requests(self, pulls):
        for data in pulls:
            heads_match = partial(match, patterns=self.heads_filter)
            pr_url = data['html_url']
            branch_url = '%s/tree/%s' % (
                data['head']['repo']['html_url'],
                data['head']['ref'],
            )
            if not heads_match(pr_url) and not heads_match(branch_url):
                logger.debug(
                    "Skipping %s (%s).", pr_url, data['head']['ref'],
                )
            else:
                yield PullRequest(self, data)

    def process_commits(self, payload):
        for entry in islice(payload, 4):
            yield Commit(self, entry['sha'], payload=entry)

    @asyncio.coroutine
    def load_settings(self):
        if self.SETTINGS:
            return

        try:
            jenkins_yml = yield from GITHUB.fetch_file_contents(
                self, 'jenkins.yml'
            )
            logger.debug("Loading settings from jenkins.yml")
        except ApiNotFoundError:
            jenkins_yml = '{}'

        if 'collaborators' in jenkins_yml or 'reviewers' in jenkins_yml:
            logger.debug("Collaborators defined manually.")
            collaborators = []
        else:
            try:
                collaborators = yield from unpaginate(
                    GITHUB.repos(self).collaborators
                )
            except ApiNotFoundError as e:
                raise UnauthorizedRepository(self) from e

        self.process_settings(
            collaborators=collaborators,
            jenkins_yml=jenkins_yml,
        )

    def process_collaborators(self, collaborators):
        return [c['login'] for c in collaborators or [] if (
            c['site_admin'] or
            c['permissions']['admin'] or
            c['permissions']['push']
        )]

    def process_settings(self, collaborators=None, jenkins_yml=None):  # noqa
        default_settings = dict(
            COLLABORATORS=self.process_collaborators(collaborators),
        )

        jenkins_yml = yaml.load(jenkins_yml or '{}')
        assert hasattr(jenkins_yml, 'items'), "Not yml dict/hash"
        settings = jenkins_yml.get('settings', {})
        assert hasattr(settings, 'items'), "Not yml dict/hash"
        if 'collaborators' not in settings and 'reviewers' in settings:
            settings['collaborators'] = settings['reviewers']
            del settings['reviewers']
        local_settings = {
            k.upper(): v
            for k, v in settings.items()
        }

        all_settings = {}
        all_settings.update(default_settings)
        all_settings.update(SETTINGS)
        all_settings.update(local_settings)

        self.SETTINGS = Bunch(**all_settings)
        self.post_process_settings()

    def post_process_settings(self):
        logger.debug("Repository settings:")
        for k, v in sorted(self.SETTINGS.items()):
            logger.debug("%s=%r", k, v)

    @retry
    def report_issue(self, title, body):
        if GITHUB.dry:
            logger.info("Would report issue '%s'", title)
            return {'number': 0}

        logger.info("Reporting issue on %s", self)
        return GITHUB.repos(self).issues.post(
            title=title, body=body,
        )

    @retry
    @asyncio.coroutine
    def set_hook(self, payload, hookid=None):  # hookaïda !
        hooks = GITHUB.repos(self).hooks
        if hookid:
            logger.info("Updating webhook for %s.", self)
            payload = yield from hooks(hookid).apatch(**payload)
        else:
            logger.info("Registering webhook for %s.", self)
            payload = yield from hooks.apost(**payload)
        return payload


class Commit(object):
    contexts_filter = parse_patterns(SETTINGS.JOBS)

    def __init__(self, repository, sha, payload=None):
        self.repository = repository
        self.sha = sha
        self.payload = payload
        self.statuses = {}

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.sha[:7])

    @property
    def date(self):
        payload = self.payload.get('commit', self.payload)
        return parse_datetime(payload['author']['date'])

    @asyncio.coroutine
    def fetch_statuses(self):
        if SETTINGS.IGNORE_STATUSES:
            logger.debug("Skip GitHub statuses for %s.", self.sha[:7])
            return {'statuses': []}
        else:
            logger.debug("Fetching statuses for %s.", self.sha[:7])
            return cached_arequest(
                GITHUB.repos(self.repository).status(self.sha),
            )

    @asyncio.coroutine
    def fetch_combined_status(self):
        payload = yield from cached_arequest(
            GITHUB.repos(self.repository).commits(self.sha).status,
        )
        return payload

    def filter_not_built_contexts(self, contexts, rebuild_failed=None):
        for context in contexts:
            status = CommitStatus(self.statuses.get(context, {}))
            # Skip failed job, unless rebuild asked and old
            if rebuild_failed and status.is_rebuildable:
                if status['updated_at'] > rebuild_failed:
                    continue
                else:
                    logger.debug(
                        "Requeue context %s failed before %s.",
                        context, rebuild_failed.strftime('%Y-%m-%d %H:%M:%S')
                    )
            elif status.get('state') == 'pending':
                # Pending context may be requeued.
                if not status.is_queueable:
                    continue
            # Other status are considerd built (success, failed, errored).
            elif status.get('state'):
                continue

            yield context

    def process_statuses(self, payload):
        self.statuses = {}
        for status in payload['statuses']:
            if not match(status['context'], self.contexts_filter):
                continue
            updated_at = parse_datetime(status.pop('updated_at'))
            status = CommitStatus(status, updated_at=updated_at)
            self.statuses[str(status)] = status
        logger.debug(
            "Got status for %s.",
            [str(c) for c in sorted(self.statuses.keys(), key=str)]
        )
        return self.statuses

    @asyncio.coroutine
    def maybe_update_status(self, status):
        status = CommitStatus(status)
        if status in self.statuses:
            if self.statuses[status] == status:
                return status

        new_status = yield from self.push_status(status)
        if new_status:
            status = CommitStatus(new_status)
            if 'updated_at' in status:
                status['updated_at'] = parse_datetime(status['updated_at'])
            self.statuses[str(status)] = status
        else:
            self.statuses.pop(str(status), None)
        return new_status

    @retry
    @asyncio.coroutine
    def push_status(self, status):
        kwargs = {
            k: status[k]
            for k in {'state', 'target_url', 'description', 'context'}
            if k in status
        }
        if GITHUB.dry:
            logger.info(
                "Would update status %s to %s/%s.",
                status, status['state'], status['description'],
            )
            if 'updated_at' in status:
                status['updated_at'] = status['updated_at'].isoformat() + 'Z'
            return status

        try:
            logger.info(
                "Set GitHub status %s to %s/%s.",
                status, status['state'], status['description'],
            )
            payload = yield from (
                GITHUB.repos(self.repository).statuses(self.sha)
                .apost(**kwargs)
            )
            return payload
        except ApiError as e:
            logger.debug('ApiError %r', e.response['json'])
            logger.warn('Hit 1000 status updates on %s.', self.sha)
            return status


class Head(object):
    contexts_filter = parse_patterns(SETTINGS.JOBS)

    _url_re = re.compile(
        r'^https://github.com/(?P<owner>[\w-]+)/(?P<name>[\w-]+)/'
        r'(?P<type>pull|tree)/(?P<id>.*)$'
    )

    @classmethod
    @asyncio.coroutine
    def from_url(cls, url):
        match = cls._url_re.match(url)
        if not match:
            raise Exception("Can't infer HEAD from %s." % (url,))

        repository = yield from Repository.from_name(
            match.group('owner'), match.group('name')
        )

        type_ = match.group('type')
        if type_ == 'pull':
            payload = yield from cached_arequest(
                GITHUB.repos(repository).pulls(match.group('id'))
            )

            return PullRequest(repository, payload)
        else:
            payload = yield from cached_arequest(
                GITHUB.repos(repository).branches(match.group('id'))
            )
            if payload['protected']:
                return Branch(repository, payload)

            payload = yield from repository.fetch_pull_requests()
            pr_map = {
                p['head']['repo']['html_url'] + '/tree/' + p['head']['ref']: p
                for p in payload
            }
            try:
                payload = pr_map[url]
            except KeyError:
                raise Exception(
                    "No open PR for unprotected branch %s." % (
                        match.group('id'),
                    ),
                )
            pr = PullRequest(repository, payload)
            logger.debug("Resolved %s.", pr)
            return pr

    def __init__(self, repository, ref, sha):
        self.repository = repository
        self.sha = sha
        self.ref = ref
        self.fullref = 'refs/heads/' + ref

    def __lt__(self, other):
        return self.sort_key() < other.sort_key()


class Branch(Head):
    def __init__(self, repository, payload):
        super(Branch, self).__init__(
            repository=repository,
            ref=payload['name'],
            sha=payload['commit']['sha'],
        )
        self.payload = payload

    def sort_key(self):
        # Sort by not urgent, type branche, branche name
        return True, 100, self.ref

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.ref)

    def __str__(self):
        return '%s (%s)' % (self.url, self.sha[:7])

    def __eq__(self, other):
        return self.url == other.url

    def __hash__(self):
        return hash(self.url)

    @property
    def url(self):
        return 'https://github.com/%s/tree/%s' % (self.repository, self.ref)

    @asyncio.coroutine
    def fetch_commits(self, last_date=None):
        head = yield from cached_arequest(
            GITHUB.repos(self.repository).git.commits(self.sha)
        )
        parent = yield from cached_arequest(
            GITHUB.repos(self.repository).git
            .commits(head['parents'][0]['sha'])
        )
        return [head, parent]

    @asyncio.coroutine
    def fetch_comments(self):
        payload = yield from cached_arequest(
            GITHUB.repos(self.repository).commits(self.sha).comments
        )
        return payload

    @retry
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.repository).commits(self.sha).comments
            .post(body=body.strip())
        )


class PullRequest(Head):
    urgent_filter = parse_patterns(SETTINGS.URGENT)

    def __init__(self, repository, payload):
        super(PullRequest, self).__init__(
            repository,
            ref=payload['head']['ref'],
            sha=payload['head']['sha'],
        )
        self.payload = payload
        title = payload.get('title', '').lower()
        self.urgent = match(title, self.urgent_filter)

    def sort_key(self):
        # Return sort data. Higher is more urgent. By defaults, last PR is
        # built first. This avoid building staled PR first. It's the default
        # order of GitHub PR listing.
        return not self.urgent, 200, 0xffff - self.payload['number']

    def __str__(self):
        return '%s (%s)' % (self.url, self.ref)

    __repr__ = __str__

    @property
    def author(self):
        return self.payload['user']['login']

    @property
    def url(self):
        return self.payload['html_url']

    @asyncio.coroutine
    def fetch_commits(self, last_date=None):
        logger.debug("Fetching previous commits.")
        payload = yield from cached_arequest(
            GITHUB.repos(self.repository)
            .compare(urlquote("%s...%s" % (
                self.payload['base']['label'],
                self.payload['head']['label'],
            )))
        )
        return reversed(payload['commits'])

    @retry
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.repository).issues(self.payload['number'])
            .comments.post(body=body)
        )

    @retry
    def delete_branch(self):
        if GITHUB.dry:
            return logger.info("Would delete branch %s", self.ref)

        logger.warn("Deleting branch %s.", self.ref)
        GITHUB.repos(self.repository).git.refs.heads(self.ref).delete()

    @asyncio.coroutine
    def fetch_comments(self):
        # PR updated_at match the latest change of PR, not the date of edition
        # of the description. So, fall back to creation date.
        description = dict(self.payload, updated_at=self.payload['created_at'])
        issue = GITHUB.repos(self.repository).issues(self.payload['number'])
        comments = yield from cached_arequest(issue.comments)
        return [description] + comments

    @retry
    def merge(self, message=None):
        body = {
            'sha': self.payload['head']['sha'],
        }

        if GITHUB.dry:
            return logger.info("Would merge %s", body['sha'])

        logger.warn("Merging %s!", self)
        (
            GITHUB.repos(self.repository).pulls(self.payload['number']).merge
            .put(body=body)
        )


class WebHook(dict):
    def __eq__(self, other):
        selfconfig = {
            k: v for k, v in self['config'].items() if k != 'secret'
        }
        otherconfig = {
            k: v for k, v in other['config'].items() if k != 'secret'
        }
        return (
            self['name'] == other['name'] and
            self['active'] == other['active'] and
            selfconfig == otherconfig and
            self["events"] == other["events"]
        )
