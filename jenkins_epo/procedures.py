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

import itertools
import logging

from .github import GITHUB, cached_request
from .repository import Repository
from .settings import SETTINGS
from .utils import retry


logger = logging.getLogger(__name__)


def iter_heads():
    queues = []

    for repository in list_repositories():
        branches = repository.fetch_protected_branches()
        pulls = repository.fetch_pull_requests()
        heads = reversed(sorted(itertools.chain(
            repository.process_protected_branches(branches),
            repository.process_pull_requests(pulls),
        ), key=lambda head: head.sort_key()))

        # Yield first head of the repository before loading next repositories.
        queue = iter(heads)
        try:
            yield next(heads)
        except StopIteration:
            continue
        else:
            queues.append(queue)

    while queues:
        for queue in queues[:]:
            try:
                yield next(queue)
            except (GeneratorExit, StopIteration):
                queues.remove(queue)


def list_repositories(with_settings=False):
    repositories = set()

    env_repos = filter(
        None,
        SETTINGS.REPOSITORIES.replace(' ', ',').split(',')
    )
    for repository in env_repos:
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

        repositories.add(repository)
        logger.debug("Managing %s.", repository)
        yield repository


@retry(wait_fixed=15000)
def whoami():
    user = cached_request(GITHUB.user)
    logger.info(
        "I'm @%s on GitHub. %s remaining API calls.",
        user['login'], GITHUB.x_ratelimit_remaining,
    )
    return user['login']
