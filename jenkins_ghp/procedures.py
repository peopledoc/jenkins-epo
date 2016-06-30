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
from .repository import PullRequest, Repository
from .settings import SETTINGS
from .utils import match, retry


logger = logging.getLogger('jenkins_ghp')


pr_filter = [p for p in str(SETTINGS.GHP_PR).split(',') if p]


@retry(wait_fixed=15000)
def list_pulls(repository):
    logger.debug("Querying GitHub for %s PR.", repository)
    try:
        pulls = cached_request(GITHUB.repos(repository).pulls)
    except Exception:
        logger.exception("Failed to list PR for %s.", repository)
        return []

    pulls_o = []
    for data in pulls:
        if not match(data['html_url'], pr_filter):
            logger.debug(
                "Skipping %s (%s).", data['html_url'], data['head']['ref'],
            )
        else:
            pulls_o.append(PullRequest(repository, data))

    for pr in reversed(sorted(pulls_o, key=PullRequest.sort_key)):
        pr.fetch_commit()
        if pr.is_outdated:
            logger.debug(
                'Skipping PR %s because older than %s weeks.',
                pr, SETTINGS.GHP_COMMIT_MAX_WEEKS,
            )
        else:
            yield pr


def list_repositories(with_settings=False):
    repositories = {}
    jobs = JENKINS.get_jobs()

    env_repos = filter(None, SETTINGS.GHP_REPOSITORIES.split(' '))
    for entry in env_repos:
        repository, branches = (entry + ':').split(':', 1)
        owner, name = repository.split('/')
        repositories[repository] = Repository(owner, name)
        logger.debug("Managing %s.", repository)

    for job in jobs:
        for remote in job.get_scm_url():
            repository = Repository.from_remote(remote)
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
                repo.load_settings()
            yield repo
        except Exception as e:
            logger.error("Failed to load %s repository: %r", repository, e)


@retry(wait_fixed=15000)
def whoami():
    user = cached_request(GITHUB.user)
    logger.info("I'm @%s on GitHub.", user['login'])
    return user['login']
