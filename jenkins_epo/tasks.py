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
import logging

from .workers import WORKERS, Task


logger = logging.getLogger(__name__)


class ProcessUrlTask(Task):
    def __init__(self, priority, url, callable_):
        super(ProcessUrlTask, self).__init__(priority)
        self.url = url
        self.callable_ = callable_

    def __str__(self):
        return self.url

    def __call__(self):
        return self.callable_(self.url)


class ProcessTask(ProcessUrlTask):
    def __init__(self, head, callable_, origin='50-poll'):
        super(ProcessTask, self).__init__(
            (origin,) + head.sort_key(), head.url, callable_=callable_,
        )


class QueuerTask(Task):
    def __init__(self, repository, task_factory):
        super(QueuerTask, self).__init__(('99-poll', str(repository)))
        self.repository = repository
        self.task_factory = task_factory

    def __str__(self):
        return str(self.repository)

    @asyncio.coroutine
    def queue_heads(self, heads):
        for head in heads:
            logger.debug("Queuing %s.", head)
            yield from WORKERS.enqueue(self.task_factory(head))

    @asyncio.coroutine
    def __call__(self):
        logger.info("Fetching %s heads.", self.repository)
        branches = yield from self.repository.fetch_protected_branches()
        heads = self.repository.process_protected_branches(branches)
        yield from self.queue_heads(heads)
        pulls = yield from self.repository.fetch_pull_requests()
        heads = self.repository.process_pull_requests(pulls)
        yield from self.queue_heads(heads)


class PrinterTask(Task):
    def __init__(self, head):
        super(PrinterTask, self).__init__(('50-head', ) + head.sort_key())
        self.head = head

    def __str__(self):
        return str(self.head)

    @asyncio.coroutine
    def __call__(self):
        print(self.head)
