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

import base64
import datetime
import logging
import re

from github import GitHub, ApiError, ApiNotFoundError
from github import (
    build_opener, HTTPSHandler, HTTPError, JsonObject, Request,
    TIMEOUT, _METHOD_MAP, _URL,
    _encode_json, _encode_params, _parse_json,
)
import yaml

from .cache import CACHE
from .settings import SETTINGS
from .utils import match, parse_datetime, retry


logger = logging.getLogger(__name__)


def check_rate_limit_threshold():
    if GITHUB.x_ratelimit_remaining == -1:
        # Never queryied GitHub. We must do it once.
        return

    if GITHUB.x_ratelimit_remaining > SETTINGS.GHP_RATE_LIMIT_THRESHOLD:
        # Cool, we didn't hit our threshold
        return

    logger.debug(
        "GitHub hit rate limit threshold exceeded. (remaining=%s)",
        GITHUB.x_ratelimit_remaining,
    )
    # Fake rate limit exceeded
    raise ApiError(url='any', request={}, response=dict(code='403', json=dict(
        message="API rate limit exceeded for 0.0.0.0"
    )))


def cached_request(query, **kw):
    check_rate_limit_threshold()
    cache_key = '_gh_' + str(query._name) + '_get_' + _encode_params(kw)
    try:
        response = CACHE.get(cache_key)
        last_modified = response._headers['Last-Modified']
        logger.debug("Trying %s modified since %s", cache_key, last_modified)
        headers = {b'If-Modified-Since': last_modified}
    except (AttributeError, KeyError):
        headers = {}

    try:
        response = query.get(headers=headers, **kw)
    except ApiError as e:
        if e.response['code'] != 304:
            raise
        else:
            logger.debug(
                "Saved one rate limit hit! (remaining=%s)",
                GITHUB.x_ratelimit_remaining,
            )

    CACHE.set(cache_key, response)
    return response


class GHList(list):
    pass


class CustomGitHub(GitHub):
    def _http(self, _method, _path, headers={}, **kw):
        # Apply https://github.com/michaelliao/githubpy/pull/19
        data = None
        if _method == 'GET' and kw:
            _path = '%s?%s' % (_path, _encode_params(kw))
        if _method in ['POST', 'PATCH', 'PUT']:
            data = bytes(_encode_json(kw), 'utf-8')
        url = '%s%s' % (_URL, _path)
        opener = build_opener(HTTPSHandler)
        request = Request(url, data=data)
        request.get_method = _METHOD_MAP[_method]
        if self._authorization:
            request.add_header('Authorization', self._authorization)
        if _method in ['POST', 'PATCH', 'PUT']:
            request.add_header(
                'Content-Type', 'application/x-www-form-urlencoded'
            )
        for k, v in headers.items():
            request.add_header(k, v)
        try:
            response = opener.open(request, timeout=TIMEOUT)
            is_json = self._process_resp(response.headers)
            if is_json:
                resp = _parse_json(response.read().decode('utf-8'))
                if isinstance(resp, list):
                    resp = GHList(resp)
                resp.__dict__['_headers'] = dict(response.headers.items())
                return resp
        except HTTPError as e:
            is_json = self._process_resp(e.headers)
            if is_json:
                json = _parse_json(e.read().decode('utf-8'))
            else:
                json = e.read().decode('utf-8')
            req = JsonObject(method=_method, url=url)
            resp = JsonObject(
                code=e.code, json=json, _headers=dict(e.headers.items())
            )
            if resp.code == 404:
                raise ApiNotFoundError(url, req, resp)
            raise ApiError(url, req, resp)


class LazyGithub(object):
    def __init__(self):
        self._instance = None
        self.dry = SETTINGS.GHP_DRY_RUN or SETTINGS.GHP_GITHUB_RO

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    def load(self):
        if not self._instance:
            self._instance = CustomGitHub(access_token=SETTINGS.GITHUB_TOKEN)


GITHUB = LazyGithub()


class JobSpec(object):
    def __init__(self, project, name, data=None):
        if isinstance(data, str):
            data = dict(script=data)
        self.data = data or {}
        self.name = name
        self.project = project

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(str(self))


class Project(object):
    remote_re = re.compile(
        r'.*github.com[:/](?P<owner>[\w-]+)/(?P<repository>[\w-]+).*'
    )
    pr_filter = [p for p in SETTINGS.GHP_PR.split(',') if p]

    @classmethod
    def from_remote(cls, remote_url):
        match = cls.remote_re.match(remote_url)
        if not match:
            raise ValueError('%r is not github' % (remote_url,))
        return cls(**match.groupdict())

    def __init__(self, owner, repository, jobs=None, branches=None):
        self.owner = owner
        self.repository = repository
        self.jobs = jobs or []
        self.branches_settings = branches or []

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __str__(self):
        return '%s/%s' % (self.owner, self.repository)

    def __repr__(self):
        return '%s(%r, %r)' % (
            self.__class__.__name__, self.owner, self.repository)

    @property
    def url(self):
        return 'https://github.com/%s/%s' % (self.owner, self.repository)

    @retry(wait_fixed=15000)
    def list_branches(self):
        branches = self.branches_settings

        if not branches:
            logger.debug("No explicit branches configured for %s", self)
            return []

        logger.debug("Search remote branches matching %s", ', '.join(branches))

        ret = []
        for branch in branches:
            try:
                ref = cached_request(
                    GITHUB.repos(self.owner)(self.repository).git(branch)
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

        pulls = cached_request(
            GITHUB.repos(self.owner)(self.repository)
            .pulls, per_page=b'100',
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
            GITHUB.repos(self.project.owner)(self.project.repository)
            .commits(self.sha)
        )
        if 'commit' not in data:
            raise Exception('No commit data')

        return data['commit']

    @retry(wait_fixed=15000)
    def list_jobs(self):
        jobs = set()

        for job in self.project.jobs:
            jobs.add(job)

        try:
            config = cached_request(
                GITHUB.repos(self.project.owner)(self.project.repository)
                .contents('jenkins.yml'),
                ref=self.ref,
            )
        except ApiNotFoundError:
            # No jenkins.yml
            pass
        else:
            config = base64.b64decode(config['content']).decode('utf-8')
            config = yaml.load(config)
            for name, params in config.items():
                job = JobSpec(self.project, name, params)
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
                    GITHUB.repos(self.project.owner)(self.project.repository)
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
                GITHUB.repos(self.project.owner)(self.project.repository)
                .statuses(self.sha).post(**new_status)
            )
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
        return cached_request(
            GITHUB.repos(self.project.owner)(self.project.repository)
            .commits(self.sha).comments
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
    _urgent_re = re.compile(r'^jenkins: *urgent$', re.MULTILINE)

    def __init__(self, data, project):
        super(PullRequest, self).__init__(
            project,
            sha=data['head']['sha'],
            ref=data['head']['ref'],
        )
        self.data = data
        body = (data.get('body') or '').replace('\r', '')
        self.urgent = bool(self._urgent_re.match(body))

    def sort_key(self):
        # Return sort data. Higher is more urgent. By defaults, last PR is
        # built first. This avoid building staled PR first. It's the default
        # order of GitHub PR listing.
        return self.urgent, self.data['number']

    def __str__(self):
        return '%s (%s)' % (self.data['html_url'], self.ref)

    __repr__ = __str__

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
        return [cached_request(issue)] + cached_request(issue.comments)
