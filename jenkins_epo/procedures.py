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

import asyncio
from concurrent.futures import CancelledError
from datetime import datetime, timedelta, timezone
import logging

from .bot import Bot
from .github import GITHUB, cached_arequest
from .queuer import Queuer
from .repository import Head, Repository, UnauthorizedRepository
from .settings import SETTINGS
from .utils import retry

logger = logging.getLogger(__name__)


class HeadMessage(object):
    def __init__(self, head, me):
        self.priority = head.sort_key()
        self.url = head.url
        self.me = me

    def __lt__(self, other):
        return self.priority < other.priority

    def __str__(self):
        return self.url

    def __call__(self, *kw):
        return process_url(self.url, me=self.me)


@asyncio.coroutine
def queue_heads(queue):
    me = yield from whoami()
    repositories = list_repositories()
    queuer = Queuer(queue, lambda h: HeadMessage(h, me=me))
    yield from queuer.queue_repositories(repositories)


def list_repositories(with_settings=False):
    logger.info("Fetching repositories.")
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
            if SETTINGS.DEBUG:
                raise
            else:
                continue

        if repository in repositories:
            continue

        repositories.add(repository)
        logger.debug("Managing %s.", repository)
        yield repository


@asyncio.coroutine
def process_url(url, me=None, throttle=True):
    if throttle:
        yield from throttle_github()
    head = yield from Head.from_url(url)

    task = asyncio.Task.current_task()
    task.logging_id = head.sha[:4]

    bot = Bot(me=me)
    try:
        yield from head.repository.load_settings()
    except UnauthorizedRepository:
        logger.error("Write access denied to %s.", head.repository)
        raise

    logger.info("Working on %s.", head)
    try:
        yield from bot.run(head)
    except CancelledError:
        logger.warn("Cancelled processing %s:", head)

    logger.info("Processed %s.", head)
    del task.logging_id


@asyncio.coroutine
def whoami():
    user = yield from cached_arequest(GITHUB.user)
    logger.info("I'm @%s on GitHub.", user['login'])
    return user['login']


def compute_throttling(now, rate_limit):
    data = rate_limit['rate']
    calls_limit = data['limit'] - SETTINGS.RATE_LIMIT_THRESHOLD
    calls_remaining = data['remaining'] - SETTINGS.RATE_LIMIT_THRESHOLD
    calls_consumed = calls_limit - calls_remaining
    if calls_consumed < 200:
        return 0  # Don't throttle on first calls. Rate is unreliable.

    now = now.replace(microsecond=0)
    reset = (
        datetime
        .utcfromtimestamp(rate_limit['rate']['reset'])
        .replace(tzinfo=timezone.utc)
    )

    # https://developer.github.com/v3/#rate-limiting
    time_limit = 3600
    time_remaining = (reset - now).total_seconds()
    time_consumed = time_limit - time_remaining

    countdown = (
        calls_limit / max(1, calls_consumed) * time_consumed - time_consumed
    )
    estimated_end = now + timedelta(seconds=int(countdown))

    logger.info(
        "%d remaining API calls. Consumed at %s. Reset at %s.",
        calls_remaining,
        estimated_end.replace(tzinfo=timezone.utc),
        reset.replace(tzinfo=timezone.utc)
    )

    if countdown > time_remaining:
        return 0
    else:
        # Split processing time by slot of 30s. Sleep between them.
        slots_count = max(1, countdown / 30)
        estimated_sleep = time_remaining - countdown
        # Wait max 30m. We may still have a bug just above. :(
        return min(1800, int(estimated_sleep / slots_count))


@retry
@asyncio.coroutine
def throttle_github():
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    payload = yield from GITHUB.rate_limit.aget()
    seconds_to_wait = compute_throttling(now, payload)
    if seconds_to_wait:
        logger.warn("Throttling GitHub API calls by %ds.", seconds_to_wait)
        yield from asyncio.sleep(seconds_to_wait)
