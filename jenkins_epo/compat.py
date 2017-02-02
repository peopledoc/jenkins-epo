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
from asyncio import PriorityQueue
import sys


class JoinableQueueMixin(object):
    def __init__(self, *a, **kw):
        super(JoinableQueueMixin, self).__init__(*a, **kw)
        self._pending_tasks = 0
        self._finished = asyncio.Event()

    @asyncio.coroutine
    def put(self, *a, **kw):
        self._pending_tasks += 1
        self._finished.clear()
        out = yield from super(JoinableQueueMixin, self).put(*a, **kw)
        return out

    def task_done(self):
        self._pending_tasks -= 1
        if self._pending_tasks <= 0:
            self._finished.set()

    @asyncio.coroutine
    def join(self):
        if self._pending_tasks > 0:
            yield from self._finished.wait()


if sys.version_info < (3, 4, 4):
    class PriorityQueue(JoinableQueueMixin, PriorityQueue):
        pass
