import asyncio
import bdb
import logging
import sys

import argh

from .bot import Bot
from .jenkins import JENKINS
from .settings import SETTINGS


logger = logging.getLogger('jenkins_ghb')


def bot():
    """Poll GitHub to find something to do"""
    queue_empty = JENKINS.is_queue_empty()
    if not queue_empty:
        logger.warn("Queue is full. No jobs will be queued.")

    bot = Bot(queue_empty)
    for project in JENKINS.list_projects():
        for pr in project.list_pull_requests():
            bot.run(pr)


def list_jobs():
    """List managed jobs"""
    for project in JENKINS.list_projects():
        for job in project.jobs:
            print(job)


def list_pr():
    """List GitHub PR polled"""
    for project in JENKINS.list_projects():
        for pr in project.list_pull_requests():
            print(pr)


def list_projects():
    """List GitHub projects tested by this Jenkins"""

    for project in JENKINS.list_projects():
        print(project)


class ErrorHandler(object):
    def __init__(self):
        self.context = None

    def __call__(self, loop, context):
        self.context = context
        loop.stop()

    def exit(self):
        if not self.context:
            return 0

        exception = self.context['future'].exception()
        if isinstance(exception, bdb.BdbQuit):
            logger.debug('Graceful exit from debugger')
            return 0

        logger.critical('Unhandled error')
        self.context['future'].print_stack()

        if not SETTINGS.GHIB_DEBUG:
            return 1

        try:
            import ipdb as pdb
        except ImportError:
            import pdb

        pdb.post_mortem(exception.__traceback__)

        return 1


def main():
    parser = argh.ArghParser()
    parser.add_commands([bot, list_jobs, list_projects, list_pr])

    loop = asyncio.get_event_loop()
    error_handler = ErrorHandler()
    loop.set_exception_handler(error_handler)

    @asyncio.coroutine
    def main_iteration(loop):
        parser.dispatch(raw_output=True)

        if SETTINGS.GHIB_LOOP:
            logger.debug("Looping in %s seconds", SETTINGS.GHIB_LOOP)
            loop.call_later(SETTINGS.GHIB_LOOP, main_iteration, loop)
        else:
            loop.stop()

    asyncio.async(main_iteration(loop))
    loop.run_forever()
    loop.close()
    sys.exit(error_handler.exit())
