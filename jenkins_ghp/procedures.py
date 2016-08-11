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

from .github import GITHUB, cached_request
from .jenkins import JENKINS
from .repository import Repository
from .settings import SETTINGS
from .utils import retry


logger = logging.getLogger(__name__)


def list_repositories(with_settings=False):
    repositories = {}

    env_repos = filter(None, SETTINGS.GHP_REPOSITORIES.split(' '))
    for entry in env_repos:
        repository, branches = (entry + ':').split(':', 1)
        if repository in repositories:
            continue
        owner, name = repository.split('/')
        repositories[repository] = Repository.from_name(owner, name)
        logger.debug("Managing %s.", repository)

    jobs = JENKINS.get_jobs()
    for job in jobs:
        for remote in job.get_scm_url():
            repository = Repository.from_remote(remote)
            if repository not in repositories:
                # Maybe we have the old name, so first, resolve it.
                repository = Repository.from_name(
                    repository.owner, repository.name
                )

            if repository not in repositories:
                logger.debug("Managing %s.", repository)
                repositories[repository] = repository
            else:
                repository = repositories[repository]

            logger.info("Managing %s.", job)
            repository.jobs.append(job)
            break
        else:
            logger.debug("Skipping %s, no GitHub repository.", job)

    for repo in sorted(repositories.values(), key=str):
        try:
            if with_settings:
                logger.info("Loading %s.", repo)
                repo.load_settings()
            yield repo
        except Exception as e:
            logger.error("Failed to load %s repository: %r", repo, e)


@retry(wait_fixed=15000)
def whoami():
    user = cached_request(GITHUB.user)
    logger.info(
        "I'm @%s on GitHub. %s remaining API calls.",
        user['login'], GITHUB.x_ratelimit_remaining,
    )
    return user['login']
