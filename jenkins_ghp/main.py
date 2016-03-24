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

import argparse
import asyncio
import bdb
import functools
import inspect
import logging
import sys

from .bot import Bot
from .cache import CACHE
from .jenkins import JENKINS
from .settings import SETTINGS


logger = logging.getLogger('jenkins_ghp')


def loop(wrapped):
    if SETTINGS.GHP_LOOP:
        @asyncio.coroutine
        def wrapper(*args, **kwargs):
            while True:
                res = wrapped(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    yield from res

                logger.info("Looping in %s seconds", SETTINGS.GHP_LOOP)
                yield from asyncio.sleep(SETTINGS.GHP_LOOP)
        functools.update_wrapper(wrapper, wrapped)
        return wrapper
    else:
        return wrapped


@asyncio.coroutine
def check_queue(bot):
    if SETTINGS.GHP_ALWAYS_QUEUE:
        logger.info("Ignoring queue status. New jobs will be queued.")
        bot.queue_empty = True
        return

    old, bot.queue_empty = bot.queue_empty, JENKINS.is_queue_empty()
    if not bot.queue_empty:
        yield from asyncio.sleep(5)
        bot.queue_empty = JENKINS.is_queue_empty()
    if old == bot.queue_empty:
        return
    elif bot.queue_empty:
        logger.warn("Queue is empty. New jobs will be queued.")
    elif not bot.queue_empty:
        logger.warn("Queue is full. No jobs will be queued.")


@loop
@asyncio.coroutine
def bot():
    """Poll GitHub to find something to do"""
    bot = Bot(queue_empty=None)
    for project in JENKINS.list_projects():
        for branch in project.list_branches():
            yield from check_queue(bot)
            bot.run(branch)

        for pr in project.list_pull_requests():
            yield from check_queue(bot)
            bot.run(pr)

    CACHE.purge()


def list_jobs():
    """List managed jobs"""
    for project in JENKINS.list_projects():
        for job in project.jobs:
            print(job)


def list_branches():
    """List branches to build"""

    for project in JENKINS.list_projects():
        for branch in project.list_branches():
            print(branch)


def list_pr():
    """List GitHub PR polled"""
    for project in JENKINS.list_projects():
        for pr in project.list_pull_requests():
            print(pr)


def list_projects():
    """List GitHub projects tested by this Jenkins"""

    for project in JENKINS.list_projects():
        print(project)


def command_exitcode(command_func):
    try:
        command_func()
    except bdb.BdbQuit:
        logger.debug('Graceful exit from debugger')
        return 0
    except Exception:
        logger.exception('Unhandled error')

        if not SETTINGS.GHP_DEBUG:
            return 1

        try:
            import ipdb as pdb
        except ImportError:
            import pdb

        pdb.post_mortem(sys.exc_info()[2])
        logger.debug('Graceful exit from debugger')

        return 1


def main(argv=None):
    argv = argv or sys.argv
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND')
    for command in [bot, list_jobs, list_projects, list_branches, list_pr]:
        subparser = subparsers.add_parser(
            command.__name__.replace('_', '-'),
            help=inspect.cleandoc(command.__doc__ or '').split('\n')[0],
        )
        subparser.set_defaults(command_func=command)

    args = parser.parse_args(argv)
    try:
        command_func = args.command_func
    except AttributeError:
        command_func = parser.print_usage

    if asyncio.iscoroutinefunction(command_func):
        def run_async():
            loop = asyncio.get_event_loop()
            task = loop.create_task(command_func())
            try:
                loop.run_until_complete(task)
            except BaseException:
                if task.done():
                    task.exception()  # Consume task exception
                else:
                    task.cancel()
                loop.close()
                raise

        sys.exit(command_exitcode(run_async))
    else:
        sys.exit(command_exitcode(command_func))
