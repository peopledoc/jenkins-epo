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
from itertools import islice
import logging
from urllib.parse import quote as urlquote
import re

from github import ApiError
import yaml

from .github import cached_request, GITHUB, ApiNotFoundError
from .settings import SETTINGS
from .utils import (
    Bunch, format_duration, match, parse_datetime, parse_patterns, retry,
)


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
    def is_rebuildable(self):
        if self.get('state') in {'error', 'failure'}:
            return True
        if self.get('description') in {'Skipped', 'Disabled on Jenkins.'}:
            return True
        return False

    jenkins_status_map = {
        # Requeue an aborted job
        'ABORTED': ('error', 'Aborted!'),
        'FAILURE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'UNSTABLE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'SUCCESS': ('success', 'Build %(name)s succeeded in %(duration)s!'),
    }

    def from_build(self, build=None):
        # If no build found, this may be an old CI build, or any other
        # unconfirmed build. Retrigger.
        jenkins_status = build.get_status() if build else 'ABORTED'
        if build and jenkins_status:
            state, description = self.jenkins_status_map[jenkins_status]
            if description != 'Backed':
                description = description % dict(
                    name=build._data['displayName'],
                    duration=format_duration(build._data['duration']),
                )
            return self.__class__(self, description=description, state=state)
        else:
            # Don't touch
            return self.__class__(self)


class Repository(object):
    pr_filter = parse_patterns(SETTINGS.PR)

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
        return parse_datetime(self.payload['commit']['author']['date'])

    @property
    def is_outdated(self):
        weeks = self.repository.SETTINGS.COMMIT_MAX_WEEKS
        if not weeks:
            return False

        now = datetime.datetime.utcnow()
        age = now - self.date
        maxage = datetime.timedelta(weeks=weeks)
        return age > maxage

    @retry(wait_fixed=15000)
    def fetch_payload(self):
        logger.debug("Fetching commit %s.", self.sha[:7])
        payload = cached_request(
            GITHUB.repos(self.repository).commits(self.sha)
        )
        self.payload = payload
        return payload

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

    @retry(wait_fixed=15000)
    def fetch_combined_status(self):
        return cached_request(
            GITHUB.repos(self.repository).commits(self.sha).status,
        )

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
        return new_status

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
            return status


class Head(object):
    contexts_filter = parse_patterns(SETTINGS.JOBS)

    def __init__(self, repository, ref, sha):
        self.repository = repository
        self.sha = sha
        self.ref = ref
        self.last_commit = Commit(repository, sha, dict())

    def list_comments(self):
        raise NotImplemented


class Branch(Head):
    def __init__(self, repository, payload):
        super(Branch, self).__init__(
            repository=repository,
            ref='refs/heads/' + payload['name'],
            sha=payload['commit']['sha'],
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
    def fetch_previous_commits(self, last_date=None):
        head = cached_request(
            GITHUB.repos(self.repository).git.commits(self.sha)
        )
        yield head
        yield cached_request(
            GITHUB.repos(self.repository).git
            .commits(head['parents'][0]['sha'])
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

    def process_commits(self, payload):
        count = 0
        self.last_commit = None
        for entry in payload:
            commit = Commit(self.repository, entry['sha'], payload=entry)
            if not self.last_commit:
                self.last_commit = commit
            yield commit
            count += 1
            if count >= 4:
                return


class PullRequest(Head):
    _urgent_re = re.compile(r'^jenkins: *urgent$', re.MULTILINE)

    def __init__(self, repository, payload):
        super(PullRequest, self).__init__(
            repository,
            ref=payload['head']['ref'],
            sha=payload['head']['sha'],
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
    def fetch_previous_commits(self, last_date=None):
        logger.debug("Fetching previous commits.")
        return cached_request(GITHUB.repos(self.repository).compare(
            urlquote("%s...%s" % (
                self.payload['base']['label'],
                self.payload['head']['label'],
            ))
        ))

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

    def process_commits(self, payload):
        self.last_commit = None
        for entry in islice(reversed(payload['commits']), 4):
            commit = Commit(self.repository, entry['sha'], payload=entry)
            if not self.last_commit:
                self.last_commit = commit
            yield commit
