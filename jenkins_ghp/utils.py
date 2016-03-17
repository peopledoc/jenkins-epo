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
import fnmatch
import logging
import time

import retrying
from github import ApiError


logger = logging.getLogger(__name__)


def retry_filter(exception):
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

    if not isinstance(exception, IOError):
        return False

    logger.warn(
        "Retrying on %r: %s",
        type(exception), str(exception) or repr(exception)
    )
    return True


def retry(*dargs, **dkw):
    defaults = dict(
        retry_on_exception=retry_filter,
        wait_exponential_multiplier=500,
        wait_exponential_max=15000,
    )

    if len(dargs) == 1 and callable(dargs[0]):
        return retrying.retry(**defaults)(dargs[0])
    else:
        dkw = dict(defaults, **dkw)
        return retrying.retry(*dargs, **dkw)


def match(item, patterns):
    matched = not patterns
    for pattern in patterns:
        negate = False
        if pattern.startswith('-'):
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


def wait_rate_limit_reset():
    from .project import GITHUB
    now = int(time.time())
    wait = GITHUB.x_ratelimit_reset - now + 5
    logger.info("Waiting rate limit reset in %s seconds", wait)
    time.sleep(wait)
