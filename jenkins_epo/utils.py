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
import collections
import datetime
import fnmatch
import logging
import sys
import time

from github import ApiError
from http.client import HTTPException
import tenacity
from requests import HTTPError


logger = logging.getLogger(__name__)


class ARetrying(tenacity.Retrying):
    def __init__(self, sleep=time.sleep, *args, **kwargs):
        super(ARetrying, self).__init__(sleep=time.sleep, *args, **kwargs)

    def call(self, fn, *args, **kwargs):
        if asyncio.iscoroutinefunction(fn):
            return self.acall(fn, *args, **kwargs)
        else:
            return super(ARetrying, self).call(fn, *args, **kwargs)

    @asyncio.coroutine
    def acall(self, fn, *args, **kwargs):
        self.statistics.clear()
        start_time = tenacity.now()
        self.statistics['start_time'] = start_time
        attempt_number = 1
        self.statistics['attempt_number'] = attempt_number
        self.statistics['idle_for'] = 0
        while True:
            trial_start_time = tenacity.now()
            if self.before is not None:
                self.before(fn, attempt_number)

            fut = tenacity.Future(attempt_number)
            try:
                result = yield from fn(*args, **kwargs)
            except tenacity.TryAgain:
                trial_end_time = tenacity.now()
                retry = True
            except Exception:
                trial_end_time = tenacity.now()
                tb = sys.exc_info()
                try:
                    tenacity._utils.capture(fut, tb)
                finally:
                    del tb
                retry = self.retry(fut)
            else:
                trial_end_time = tenacity.now()
                fut.set_result(result)
                retry = self.retry(fut)

            if not retry:
                return fut.result()

            if self.after is not None:
                trial_time_taken = trial_end_time - trial_start_time
                self.after(fn, attempt_number, trial_time_taken)

            delay_since_first_attempt = tenacity.now() - start_time
            self.statistics['delay_since_first_attempt'] = \
                delay_since_first_attempt
            if self.stop(attempt_number, delay_since_first_attempt):
                if self.reraise:
                    raise tenacity.RetryError(fut).reraise()
                tenacity.six.raise_from(
                    tenacity.RetryError(fut), fut.exception()
                )

            if self.wait:
                sleep = self.wait(attempt_number, delay_since_first_attempt)
            else:
                sleep = 0
            self.statistics['idle_for'] += sleep
            self.sleep(sleep)

            attempt_number += 1
            self.statistics['attempt_number'] = attempt_number


def retry(*dargs, **dkw):
    defaults = dict(
        retry=tenacity.retry_if_exception(filter_exception_for_retry),
        wait=tenacity.wait_exponential(multiplier=500, max=15000),
    )

    if len(dargs) == 1 and callable(dargs[0]):
        def wrap_simple(f):
            def wrapped_f(*args, **kw):
                return ARetrying(**defaults).call(f, *args, **kw)
            return wrapped_f
        return wrap_simple(dargs[0])
    else:
        dkw = dict(defaults, **dkw)

        def wrap(f):
            def wrapped_f(*args, **kw):
                return ARetrying(*dargs, **dkw).call(f, *args, **kw)

            return wrapped_f

        return wrap


def filter_exception_for_retry(exception):
    from .github import wait_rate_limit_reset

    if isinstance(exception, ApiError):
        try:
            message = exception.response['json']['message']
        except KeyError:
            # Don't retry on ApiError by default. Things like 1000 status
            # update must be managed by code.
            return False
        if 'API rate limit exceeded for' in message:
            wait_rate_limit_reset()
            return True
        # If not a rate limit error, don't retry.
        return False

    if not isinstance(exception, (IOError, HTTPException, HTTPError)):
        return False

    if isinstance(exception, HTTPError):
        if exception.response.status_code < 500:
            return False

    logger.warn(
        "Retrying on %r: %s",
        type(exception), str(exception) or repr(exception)
    )
    return True


def format_duration(duration):
    duration = datetime.timedelta(seconds=duration / 1000.)
    h, m, s = str(duration).split(':')
    h, m, s = int(h), int(m), float(s)
    duration = '%.1f sec' % s
    if h or m:
        duration = '%d min %s' % (m, duration)
    if h:
        duration = '%d h %s' % (h, duration)
    return duration.replace('.0', '')


def match(item, patterns):
    matched = not patterns
    for pattern in patterns:
        negate = False
        if pattern.startswith('-') or pattern.startswith('!'):
            negate = True
            pattern = pattern[1:]
        if pattern.startswith('+'):
            pattern = pattern[1:]

        local_matched = fnmatch.fnmatch(item, pattern)
        if negate:
            matched = matched and not local_matched
        else:
            matched = matched or local_matched

    return matched


def parse_datetime(formatted):
    return datetime.datetime.strptime(
        formatted, '%Y-%m-%dT%H:%M:%SZ'
    )


def parse_patterns(raw):
    return [p for p in str(raw).split(',') if p]


class Bunch(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


def deepupdate(self, other):
    for k, v in other.items():
        if isinstance(v, collections.Mapping):
            r = deepupdate(self.get(k, {}), v)
            self[k] = r
        else:
            self[k] = other[k]
    return self
