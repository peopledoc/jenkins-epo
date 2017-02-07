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

import asyncio
import logging

from .utils import switch_coro

logger = logging.getLogger(__name__)


class Queuer(object):
    def __init__(self, queue, message_factory):
        self.queue = queue
        self.message_factory = message_factory

    @asyncio.coroutine
    def queue_head(self, head):
        logger.debug("Queuing %s.", head)
        message = self.message_factory(head)
        yield from self.queue.put(message)

    @asyncio.coroutine
    def queue_iterator(self, heads):
        for head in heads:
            yield from self.queue_head(head)
            yield from switch_coro()  # Let consumer get the new item.

    @asyncio.coroutine
    def queue_repository(self, repository):
        logger.info("Fetching %s heads.", repository)
        branches = yield from repository.fetch_protected_branches()
        yield from self.queue_iterator(
            repository.process_protected_branches(branches),
        )
        pulls = yield from repository.fetch_pull_requests()
        yield from self.queue_iterator(
            repository.process_pull_requests(pulls),
        )

    @asyncio.coroutine
    def queue_repositories(self, repositories):
        loop = asyncio.get_event_loop()
        tasks = []
        # Parallelize HEADS fetching.
        for repository in repositories:
            task = loop.create_task(self.queue_repository(repository))
            tasks.append(task)
            yield from switch_coro()
        yield from asyncio.gather(*tasks)
