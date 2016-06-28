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

from .utils import Bunch


logger = logging.getLogger(__name__)


class EnvironmentSettings(Bunch):
    def __init__(self, defaults):
        logger.debug("Global settings:")
        self.load(defaults)
        logger.debug("Environment loaded.")

    def load(self, defaults):
        for k, v in sorted(defaults.items()):
            v = os.environ.get(k, v)
            try:
                v = int(v)
            except (TypeError, ValueError):
                pass
            self[k] = v
            logger.debug("%s=%r", k, v)


SETTINGS = EnvironmentSettings(defaults={
    'GHP_ALWAYS_QUEUE': False,
    'GHP_CACHE_PATH': '.ghp-cache',
    'GHP_COMMIT_MAX_WEEKS': '',
    # Drop into Pdb on unhandled exception
    'GHP_DEBUG': False,
    # Do not trigger jobs nor touch GitHub statuses.
    'GHP_DRY_RUN': False,
    # Whether to touch GitHub statuses or not
    'GHP_GITHUB_RO': False,
    'GHP_IGNORE_STATUSES': '',
    'GHP_JOBS': '',
    'GHP_JOBS_AUTO': True,
    'GHP_JOBS_COMMAND': 'jenkins-yml-runner',
    # Jenkins credentials used to clone
    'GHP_JOBS_CREDENTIALS': None,
    # Jenkins node/label
    'GHP_JOBS_NODE': 'ghp',
    # Trigger loop
    'GHP_LOOP': 0,
    # When commenting on PR
    'GHP_NAME': 'Jenkins GitHub Builder',
    'GHP_PR': '',
    'GHP_RATE_LIMIT_THRESHOLD': 250,
    # List repositories and their main branches:
    #   'owner/repo1:master owner/repo2:master,stable'
    'GHP_REPOSITORIES': '',
    'GHP_VERBOSE': '',
    'GITHUB_TOKEN': None,
    'JENKINS_URL': 'http://localhost:8080',
})
