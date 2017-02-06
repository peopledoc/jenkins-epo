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
# This file implements a simple async worker pool.

import asyncio
import logging

from .compat import PriorityQueue
from .settings import SETTINGS
from .utils import switch_coro


logger = logging.getLogger(__name__)


class WorkerPool(object):
    def __init__(self):
        self.tasks = []
        self.queue = None

    @asyncio.coroutine
    def start(self):
        loop = asyncio.get_event_loop()
        self.queue = PriorityQueue(maxsize=1024)
        for i in range(SETTINGS.CONCURRENCY):
            task = loop.create_task(self.worker(i))
            self.tasks.append(task)
            yield from switch_coro()  # Let worker start
        return self.queue

    @asyncio.coroutine
    def worker(self, id_):
        loop = asyncio.get_event_loop()
        asyncio.Task.current_task().logging_id = 'wk%02d' % (id_,)

        while True:
            logger.debug("Worker %d waiting.", id_)
            item = yield from self.queue.get()
            logger.debug("Worker %d working on %s.", id_, item)
            task = loop.create_task(item())
            try:
                yield from task
            except Exception as e:
                logger.error("Failed to process %s: %s", item, e)
            finally:
                self.queue.task_done()

    @asyncio.coroutine
    def terminate(self):
        pending_workers = [t for t in self.tasks if not t.done()]
        logger.info("Stopping pending workers.")
        for task in pending_workers:
            if not task.done():
                task.cancel()


WORKERS = WorkerPool()
