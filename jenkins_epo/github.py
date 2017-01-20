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
import base64
from datetime import datetime, timezone
import logging
import os.path
import sys
import time

import aiohttp
from github import GitHub, ApiError, ApiNotFoundError, _Callable, _Executable
from github import (
    build_opener, HTTPSHandler, HTTPError, JsonObject, Request,
    TIMEOUT, _METHOD_MAP, _URL,
    _encode_json, _encode_params, _parse_json,
)

from .cache import CACHE
from .settings import SETTINGS
from .utils import retry


logger = logging.getLogger(__name__)


@retry
def wait_rate_limit_reset(now):
    reset = (
        datetime.utcfromtimestamp(GITHUB.x_ratelimit_reset)
        .replace(tzinfo=timezone.utc)
    )
    delta = reset - now
    wait = int(delta.seconds * .9)
    waited = 0
    logger.warning("Waiting rate limit reset in %s seconds.", wait)
    time.sleep(wait)
    waited += wait
    GITHUB.rate_limit.get()
    return waited


def check_rate_limit_threshold():
    if GITHUB.x_ratelimit_remaining == -1:
        # Never queryied GitHub. We must do it once.
        return

    if GITHUB.x_ratelimit_remaining > SETTINGS.RATE_LIMIT_THRESHOLD:
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


def _cached_request_middleware(query, **kw):
    check_rate_limit_threshold()
    cache_key = '_'.join([
        'gh', SETTINGS.GITHUB_TOKEN[:8], str(query._name), _encode_params(kw),
    ])
    headers = {
        b'Accept': b'application/vnd.github.loki-preview+json',
    }
    try:
        response = CACHE.get(cache_key)
        etag = response._headers['ETag']
        headers[b'If-None-Match'] = etag
    except (AttributeError, KeyError):
        pass

    try:
        response = yield headers
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


@retry
def cached_request(query, **kw):
    generator = _cached_request_middleware(query, **kw)
    headers = next(generator)
    kw = dict(per_page=b'100', **kw)
    try:
        response = query.get(headers=headers, **kw)
    except Exception as e:
        callable, args = generator.throw, sys.exc_info()
    else:
        callable, args = generator.send, (response,)

    try:
        callable(*args)
    except StopIteration as e:
        return e.value


@retry
@asyncio.coroutine
def cached_arequest(query, **kw):
    generator = _cached_request_middleware(query, **kw)
    headers = next(generator)
    kw = dict(per_page=b'100', **kw)
    try:
        response = yield from query.aget(headers=headers, **kw)
    except Exception as e:
        callable, args = generator.throw, sys.exc_info()
    else:
        callable, args = generator.send, (response,)

    try:
        callable(*args)
    except StopIteration as e:
        return e.value


class GHList(list):
    pass


class AExecutable(_Executable):
    def __call__(self, **kw):
        return self._gh.ahttp(self._method, self._path, **kw)


class ACallable(_Callable):
    _methods = {'get', 'delete', 'patch', 'post', 'put'}

    def __call__(self, attr):
        return self.__getattr__(attr)

    def __getattr__(self, attr):
        attr = str(attr)
        if attr in self._methods:
            return _Executable(self._gh, attr.upper(), self._name)
        if attr[0] == 'a' and attr[1:] in self._methods:
            return AExecutable(self._gh, attr[1:].upper(), self._name)
        return self.__class__(self._gh, '%s/%s' % (self._name, attr))


class CustomGitHub(GitHub):
    def __getattr__(self, attr):
        return ACallable(self, '/%s' % attr)

    @asyncio.coroutine
    def ahttp(self, _method, _path, headers={}, **kw):
        url = '%s%s' % (_URL, _path)
        headers = headers or {}
        if self._authorization:
            headers['Authorization'] = self._authorization

        pre_rate_limit = self.x_ratelimit_remaining
        logger.debug(
            "%s %s (remaining=%s)",
            _method, url, self.x_ratelimit_remaining,
        )

        headers = {
            str(k): str(v)
            for k, v in headers.items()
        }

        session = aiohttp.ClientSession()
        try:
            response = yield from session.get(url, headers=headers)
            payload = yield from response.json()
        finally:
            logger.debug("Closing HTTP session.")
            yield from session.close()
        self._process_resp(response.headers)
        post_rate_limit = self.x_ratelimit_remaining
        if pre_rate_limit > 0 and pre_rate_limit < post_rate_limit:
            logger.info(
                "GitHub rate limit reset. %d calls remained.",
                pre_rate_limit,
            )

        payload['_headers'] = dict(response.headers.items())
        return payload

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
            pre_rate_limit = self.x_ratelimit_remaining
            logger.debug(
                "%s %s (remaining=%s)",
                _method, url, self.x_ratelimit_remaining,
            )

            response = opener.open(request, timeout=TIMEOUT)
            is_json = self._process_resp(response.headers)

            post_rate_limit = self.x_ratelimit_remaining
            if pre_rate_limit > 0 and pre_rate_limit < post_rate_limit:
                logger.info(
                    "GitHub rate limit reset. %d calls remained.",
                    pre_rate_limit,
                )

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
        self.dry = SETTINGS.DRY_RUN or SETTINGS.GITHUB_RO

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    def load(self):
        if not self._instance:
            self._instance = CustomGitHub(access_token=SETTINGS.GITHUB_TOKEN)

    @retry
    def fetch_file_contents(self, repository, path, **kwargs):
        path = os.path.normpath(path)
        payload = cached_request(
            self.repos(repository).contents(path), **kwargs
        )
        return base64.b64decode(payload['content']).decode('utf-8')


GITHUB = LazyGithub()
