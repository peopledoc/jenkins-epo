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
#
# This file implements an asyncio loop watch dog. Detect loop block and restart
# it.

import asyncio
from concurrent.futures import CancelledError
import logging
import signal

from .settings import SETTINGS


logger = logging.getLogger(__name__)


class WatchDog(object):
    timeout = SETTINGS.WATCHDOG

    def __init__(self):
        self.start_loop = True
        self.pulse = None
        self.heartbeat_handle = None

    def __enter__(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.heartbeat_handle = None
        if self.timeout:
            self.heartbeat()
            signal.signal(signal.SIGALRM, self.watch)
            self.watch(signal.SIGALRM, None)
        return loop

    def __exit__(self, *args, **kwargs):
        signal.alarm(0)
        if self.heartbeat_handle:
            self.heartbeat_handle.cancel()
        asyncio.get_event_loop().close()

    def heartbeat(self):
        loop = asyncio.get_event_loop()
        logger.debug("Asyncio loop is alive.")
        self.pulse = loop.time()
        # call_later is not precise, and since we mix sync and async, we can
        # easily get pulse very late.
        delay = self.timeout / 5
        self.heartbeat_handle = loop.call_later(delay, self.heartbeat)

    def watch(self, signum, frame):
        loop = asyncio.get_event_loop()
        now = loop.time()
        delay = now - self.pulse
        if delay < self.timeout:
            logger.debug("Asyncio loop watchdog is happy!")
            signal.alarm(self.timeout)
            return

        logger.warning("Detected dead loop. Restarting.")
        self.start_loop = True
        for task in asyncio.Task.all_tasks():
            logger.debug("Cancelling %s.", task)
            task.cancel()

    @asyncio.coroutine
    def wrapper(self, callable_, *args, **kwargs):
        try:
            yield from callable_(*args, **kwargs)
        except CancelledError:
            pass

    def run(self, callable_, *args, **kwargs):
        while self.start_loop:
            self.start_loop = False
            with self as loop:
                logger.debug("Running async loop.")
                coro = self.wrapper(callable_, *args, **kwargs)
                try:
                    loop.run_until_complete(coro)
                    break
                except (CancelledError, RuntimeError):
                    pass
