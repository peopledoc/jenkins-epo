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
import functools
import logging

from retrying import retry


logger = logging.getLogger(__name__)


def retry_blacklist(exception):
    if not isinstance(exception, IOError):
        return False

    logger.warn(
        "Retrying on %r: %s",
        type(exception).__name__,
        str(exception) or repr(exception)
    )
    return True


retry = functools.partial(
    retry,
    retry_on_exception=retry_blacklist,
    wait_exponential_multiplier=500,
    wait_exponential_max=10000,
)


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
