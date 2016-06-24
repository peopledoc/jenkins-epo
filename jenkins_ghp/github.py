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
import os.path
import logging

from github import GitHub, ApiError, ApiNotFoundError
from github import (
    build_opener, HTTPSHandler, HTTPError, JsonObject, Request,
    TIMEOUT, _METHOD_MAP, _URL,
    _encode_json, _encode_params, _parse_json,
)

from .cache import CACHE
from .settings import SETTINGS
from .utils import retry


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
    headers = {
        b'Accept': b'application/vnd.github.loki-preview+json',
    }
    try:
        response = CACHE.get(cache_key)
        last_modified = response._headers['Last-Modified']
        headers[b'If-Modified-Since'] = last_modified
    except (AttributeError, KeyError):
        pass

    try:
        response = query.get(headers=headers, **kw)
    except ApiError as e:
        if e.response['code'] != 304:
            raise
        else:
            logger.debug(
                "Cache up to date (remaining=%s)",
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
            logger.debug(
                "%s %s (remaining=%s)",
                _method, url, self.x_ratelimit_remaining,
            )
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
            if resp.code == 307:
                return self._http(
                    _method, json.url[len('https://api.github.com'):],
                    headers, **kw
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

    @retry(wait_fixed=15000)
    def fetch_file_contents(self, repository, path, **kwargs):
        path = os.path.normpath(path)
        items = path.split('/')

        # We walk to avoid 404, it consumes rate limit. Each step is cached.
        search = ''
        for needle in items:
            out = cached_request(
                self.repos(repository).contents(search), **kwargs
            )

            if needle == items[-1]:
                type_ = 'file'
            else:
                type_ = 'dir'
            entries = [x['name'] for x in out if x['type'] == type_]

            if needle not in entries:
                logger.debug("%s not found", path)
                raise ApiNotFoundError(path, {}, {})
            search = (search + '/' + needle).strip('/')

        payload = cached_request(self.repos(repository).contents(path))
        return base64.b64decode(payload['content']).decode('utf-8')


GITHUB = LazyGithub()


class GitHubRequests(object):

    @staticmethod
    @retry(wait_fixed=15000)
    def fetch_settings(repository):
        try:
            ghp_yml = GITHUB.fetch_file_contents(repository, '.github/ghp.yml')
            logger.debug("Loading settings from .github/ghp.yml")
        except ApiNotFoundError:
            ghp_yml = None

        collaborators = cached_request(GITHUB.repos(repository).collaborators)
        branches = cached_request(
            GITHUB.repos(repository).branches, protected='true',
        )

        repository.load_settings(
            branches=branches,
            collaborators=collaborators,
            ghp_yml=ghp_yml,
        )

    @staticmethod
    @retry(wait_fixed=15000)
    def list_branches(repository):
        branches = repository.SETTINGS.GHP_BRANCHES
        if not branches:
            logger.debug("No explicit branches configured for %s", repository)
            return []

        for branch in branches:
            logger.debug("Search remote branch %s", branch)
            try:
                ref = cached_request(GITHUB.repos(repository).git(branch))
            except ApiNotFoundError:
                logger.warn("Branch %s not found in %s", branch, repository)
                continue

            sha = ref['object']['sha']
            logger.debug("Fetching commit %s", sha[:7])
            data = cached_request(GITHUB.repos(repository).commits(sha))
            commit = data['commit']
            branch = repository.load_branch(ref, commit)
            if branch.is_outdated:
                logger.debug(
                    'Skipping branch %s because older than %s weeks',
                    branch, repository.SETTINGS.GHP_COMMIT_MAX_WEEKS,
                )
                continue
            yield branch
