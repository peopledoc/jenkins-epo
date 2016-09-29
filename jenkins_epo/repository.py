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

import datetime
import logging
import re

from github import ApiError
import yaml

from .github import cached_request, GITHUB, ApiNotFoundError
from .settings import SETTINGS
from .utils import Bunch, match, parse_datetime, retry


logger = logging.getLogger(__name__)


class CommitStatus(dict):
    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        elif isinstance(other, dict):
            known_keys = {'context', 'description', 'state', 'target_url'}
            a = {k: self[k] for k in known_keys}
            b = {k: other[k] for k in known_keys}
            return a == b
        else:
            raise TypeError("Can't compare with %s.", type(other))

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self['state'])

    def __str__(self):
        return self['context']

    def __hash__(self):
        return hash(str(self))


class Repository(object):
    pr_filter = [p for p in str(SETTINGS.PR).split(',') if p]

    remote_re = re.compile(
        r'.*github.com[:/](?P<owner>[\w-]+)/(?P<name>[\w-]+).*'
    )

    @classmethod
    @retry(wait_fixed=15000)
    def from_name(cls, owner, name):
        data = cached_request(GITHUB.repos(owner)(name))
        return cls(owner=data['owner']['login'], name=data['name'])

    @classmethod
    def from_remote(cls, remote_url):
        match = cls.remote_re.match(remote_url)
        if not match:
            raise ValueError('%r is not github' % (remote_url,))
        return cls.from_name(**match.groupdict())

    def __init__(self, owner, name, jobs=None):
        self.owner = owner
        self.name = name
        self.jobs = jobs or {}
        self.SETTINGS = Bunch()

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
    def fetch_protected_branches(self):
        logger.debug("Querying GitHub for %s protected branches.", self)
        return cached_request(GITHUB.repos(self).branches, protected='true')

    @retry(wait_fixed=15000)
    def fetch_pull_requests(self):
        logger.debug("Querying GitHub for %s PR.", self)
        return cached_request(GITHUB.repos(self).pulls)

    def process_protected_branches(self, branches):
        for branch in branches:
            yield Branch(self, branch)

    def process_pull_requests(self, pulls):
        for data in pulls:
            if not match(data['html_url'], self.pr_filter):
                logger.debug(
                    "Skipping %s (%s).", data['html_url'], data['head']['ref'],
                )
            else:
                yield PullRequest(self, data)

    @retry(wait_fixed=15000)
    def load_settings(self):
        if self.SETTINGS:
            return

        try:
            jenkins_yml = GITHUB.fetch_file_contents(self, 'jenkins.yml')
            logger.debug("Loading settings from jenkins.yml")
        except ApiNotFoundError:
            jenkins_yml = '{}'

        if 'reviewers' in jenkins_yml:
            logger.debug("Reviewers defined manually.")
            collaborators = []
        else:
            collaborators = cached_request(GITHUB.repos(self).collaborators)

        self.process_settings(
            collaborators=collaborators,
            jenkins_yml=jenkins_yml,
        )

    def process_reviewers(self, collaborators):
        return [c['login'] for c in collaborators or [] if (
            c['site_admin'] or
            c['permissions']['admin'] or
            c['permissions']['push']
        )]

    def process_settings(self, collaborators=None, jenkins_yml=None):  # noqa
        default_settings = dict(
            REVIEWERS=self.process_reviewers(collaborators),
        )

        jenkins_yml = yaml.load(jenkins_yml or '{}')
        assert hasattr(jenkins_yml, 'items'), "Not yml dict/hash"
        settings = jenkins_yml.get('settings', {})
        assert hasattr(settings, 'items'), "Not yml dict/hash"
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

    @retry(wait_fixed=15000)
    def report_issue(self, title, body):
        if GITHUB.dry:
            logger.info("Would report issue '%s'", title)
            return {'number': 0}

        logger.info("Reporting issue on %s", self)
        return GITHUB.repos(self).issues.post(
            title=title, body=body,
        )


class Head(object):
    contexts_filter = [p for p in SETTINGS.JOBS.split(',') if p]

    def __init__(self, repository, ref, sha, commit):
        self.repository = repository
        self.sha = sha
        self.ref = ref
        self.commit = commit
        self._status_cache = None

    @property
    def is_outdated(self):
        weeks = self.repository.SETTINGS.COMMIT_MAX_WEEKS
        if not weeks:
            return False

        now = datetime.datetime.utcnow()
        age = now - parse_datetime(self.commit['author']['date'])
        maxage = datetime.timedelta(weeks=weeks)
        return age > maxage

    @retry(wait_fixed=15000)
    def fetch_commit(self):
        logger.debug("Fetching commit %s.", self.sha[:7])
        payload = cached_request(
            GITHUB.repos(self.repository).commits(self.sha)
        )
        self.commit = payload['commit']
        return self.commit

    @retry(wait_fixed=15000)
    def fetch_combined_status(self):
        return cached_request(
            GITHUB.repos(self.repository).commits(self.sha).status,
        )

    @retry(wait_fixed=15000)
    def fetch_statuses(self):
        if SETTINGS.IGNORE_STATUSES:
            logger.debug("Skip GitHub statuses.")
            return {'statuses': []}
        else:
            logger.debug("Fetching statuses for %s.", self.sha[:7])
            return cached_request(
                GITHUB.repos(self.repository).status(self.sha),
            )

    def list_comments(self):
        raise NotImplemented

    def filter_not_built_contexts(self, contexts, rebuild_failed=None):
        not_built = []
        for context in contexts:
            status = self.statuses.get(context, CommitStatus())
            state = status.get('state')
            description = status.get('description')
            # Skip failed job, unless rebuild asked and old
            if state in {'error', 'failure'} or description == 'Skipped':
                if not rebuild_failed:
                    continue
                elif status['updated_at'] > rebuild_failed:
                    continue
                else:
                    logger.debug(
                        "Requeue context %s failed before %s.",
                        context, rebuild_failed.strftime('%Y-%m-%d %H:%M:%S')
                    )
            # Skip `Backed`, `New` and `Queued` jobs
            elif state == 'pending':
                # Jenkins deduplicate jobs in the queue. So it's safe to keep
                # triggering the job in case the queue was flushed.
                if description not in {'Backed', 'New', 'Queued'}:
                    continue
            # Skip other known states
            elif state:
                continue

            not_built.append(context)

        return not_built

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

    def maybe_update_status(self, status):
        if status in self.statuses:
            if self.statuses[status] == status:
                return status

        new_status = self.push_status(status)
        if new_status:
            status = CommitStatus(new_status)
            if 'updated_at' in status:
                status['updated_at'] = parse_datetime(status['updated_at'])
            self.statuses[str(status)] = status
        else:
            self.statuses.pop(str(status), None)

    @retry(wait_fixed=15000)
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
            return (
                GITHUB.repos(self.repository).statuses(self.sha).post(**kwargs)
            )
        except ApiError as e:
            logger.debug('ApiError %r', e.response['json'])
            logger.warn('Hit 1000 status updates on %s.', self.sha)


class Branch(Head):
    def __init__(self, repository, payload, commit=None):
        super(Branch, self).__init__(
            repository=repository,
            ref='refs/heads/' + payload['name'],
            sha=payload['commit']['sha'],
            commit=commit,
        )
        self.payload = payload

    def sort_key(self):
        # Sort by not urgent, type branche, branche name
        return False, 100, self.ref

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.ref)

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
            GITHUB.repos(self.repository).commits(self.sha).comments
        )

    @retry(wait_fixed=15000)
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.repository).commits(self.sha).comments
            .post(body=body.strip())
        )


class PullRequest(Head):
    _urgent_re = re.compile(r'^jenkins: *urgent$', re.MULTILINE)

    def __init__(self, repository, payload, commit=None):
        super(PullRequest, self).__init__(
            repository,
            sha=payload['head']['sha'],
            ref=payload['head']['ref'],
            commit=commit,
        )
        self.payload = payload
        body = (payload.get('body') or '').replace('\r', '')
        self.urgent = bool(self._urgent_re.search(body))

    def sort_key(self):
        # Return sort data. Higher is more urgent. By defaults, last PR is
        # built first. This avoid building staled PR first. It's the default
        # order of GitHub PR listing.
        return self.urgent, 50, self.payload['number']

    def __str__(self):
        return '%s (%s)' % (self.payload['html_url'], self.ref)

    __repr__ = __str__

    @property
    def author(self):
        return self.payload['user']['login']

    @retry(wait_fixed=15000)
    def comment(self, body):
        if GITHUB.dry:
            return logger.info("Would comment on %s", self)

        logger.info("Commenting on %s", self)
        (
            GITHUB.repos(self.repository).issues(self.payload['number'])
            .comments.post(body=body)
        )

    @retry(wait_fixed=15000)
    def delete_branch(self):
        if GITHUB.dry:
            return logger.info("Would delete branch %s", self.ref)

        logger.warn("Deleting branch %s.", self.ref)
        GITHUB.repos(self.repository).git.refs.heads(self.ref).delete()

    @retry(wait_fixed=15000)
    def list_comments(self):
        logger.debug("Queyring comments for instructions")
        issue = GITHUB.repos(self.repository).issues(self.payload['number'])
        return [self.payload] + cached_request(issue.comments)

    @retry(wait_fixed=15000)
    def merge(self, message=None):
        body = {
            'sha': self.payload['head']['sha'],
        }

        if GITHUB.dry:
            return logger.info("Would merge %s", body['sha'])

        logger.debug("Trying merge!")
        (
            GITHUB.repos(self.repository).pulls(self.payload['number']).merge
            .put(body=body)
        )
