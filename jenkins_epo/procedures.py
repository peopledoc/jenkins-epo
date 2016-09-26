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

import logging

from .github import GITHUB, cached_request
from .repository import Repository
from .settings import SETTINGS
from .utils import retry


logger = logging.getLogger(__name__)


def list_repositories(with_settings=False):
    repositories = {}

    env_repos = filter(None, SETTINGS.REPOSITORIES.split(' '))
    for entry in env_repos:
        repository, branches = (entry + ':').split(':', 1)
        if repository in repositories:
            continue
        owner, name = repository.split('/')
        try:
            repository = Repository.from_name(owner, name)
        except Exception as e:
            logger.warn("Failed to fetch repo %s: %s", repository, e)
            continue

        if repository in repositories:
            continue

        repositories[repository] = repository
        logger.debug("Managing %s.", repository)

        try:
            if with_settings:
                logger.info("Loading %s.", repository)
                repository.load_settings()
            yield repository
        except Exception as e:
            logger.error("Failed to load %s repository: %r", repository, e)


@retry(wait_fixed=15000)
def whoami():
    user = cached_request(GITHUB.user)
    logger.info(
        "I'm @%s on GitHub. %s remaining API calls.",
        user['login'], GITHUB.x_ratelimit_remaining,
    )
    return user['login']
