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
from datetime import datetime, timedelta, timezone
import logging

from .bot import Bot
from .github import GITHUB, cached_arequest
from .repository import Repository, REPOSITORIES, Head, UnauthorizedRepository
from .settings import SETTINGS
from .tasks import PrinterTask, ProcessTask, RepositoryPollerTask
from .utils import match, retry, log_context
from .workers import WORKERS

logger = logging.getLogger(__name__)


def process_task_factory(head):
    return ProcessTask(head, callable_=process_url)


@asyncio.coroutine
def poll():
    yield from whoami()
    while True:
        logger.info("Polling repositories.")
        for qualname in REPOSITORIES:
            yield from WORKERS.enqueue(
                RepositoryPollerTask(qualname, process_task_factory)
            )
        logger.info("Waiting for workers to consume queue.")
        yield from WORKERS.queue.join()
        logger.info("Delaying next poll by %ss.", SETTINGS.POLL_INTERVAL)
        yield from asyncio.sleep(SETTINGS.POLL_INTERVAL)


@asyncio.coroutine
def print_heads():
    for qualname in REPOSITORIES:
        yield from WORKERS.enqueue(
            RepositoryPollerTask(qualname, task_factory=PrinterTask)
        )
    yield from WORKERS.queue.join()


_task_map = {}


@asyncio.coroutine
def process_url(url, throttle=True):
    if not match(url, Repository.heads_filter):
        logger.debug("Skipping %s. Filtered.", url)
        return

    task = asyncio.Task.current_task()
    running_task = _task_map.get(url)
    if running_task and not running_task.done():
        logger.debug("Cancelling current task on %s.", url)
        running_task.cancel()
    _task_map[url] = task

    if throttle:
        yield from throttle_github()
    head = yield from Head.from_url(url)
    if head.repository not in REPOSITORIES:
        logger.error("%s not managed.", head.repository)
        return
    log_context(head)
    logger.info("Working on %s.", head)

    bot = Bot()
    try:
        yield from head.repository.load_settings()
    except UnauthorizedRepository:
        logger.error("Write access denied to %s.", head.repository)
        return

    yield from bot.run(head)
    logger.info("Processed %s.", head)

    del task.logging_id
    del _task_map[url]


@asyncio.coroutine
def whoami():
    if not isinstance(GITHUB.me, str):
        user = yield from cached_arequest(GITHUB.user)
        logger.info("I'm @%s on GitHub.", user['login'])
        GITHUB.me = user['login']
    return GITHUB.me


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
