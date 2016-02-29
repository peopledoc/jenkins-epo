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

import logging
import os


logger = logging.getLogger(__name__)


class EnvironmentSettings(object):
    def __init__(self, defaults):
        self.load(defaults)
        logger.debug("Environment loaded.")

    def load(self, defaults):
        for k, v in sorted(defaults.items()):
            v = os.environ.get(k, v)
            try:
                v = int(v)
            except (TypeError, ValueError):
                pass
            setattr(self, k, v)
            logger.debug("%s=%r", k, v)


SETTINGS = EnvironmentSettings(defaults={
    # Drop into Pdb on unhandled exception
    'GHP_DEBUG': False,
    # Do not trigger jobs nor touch GitHub statuses.
    'GHP_DRY_RUN': False,
    'GHP_IGNORE_STATUSES': '',
    'GHP_LIMIT_JOBS': '',
    'GHP_LIMIT_PR': '',
    # Trigger loop
    'GHP_LOOP': 0,
    # When commenting on PR
    'GHP_NAME': 'Jenkins GitHub Builder',
    'GHP_VERBOSE': '',
    'GITHUB_TOKEN': None,
    'JENKINS_URL': 'http://localhost:8080',
})
