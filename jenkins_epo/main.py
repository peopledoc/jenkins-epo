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

import argparse
import asyncio
import bdb
import functools
import inspect
import logging
import sys


from .bot import Bot
from .cache import CACHE
from .github import GITHUB
from .jenkins import JENKINS
from .settings import SETTINGS
from . import procedures


logger = logging.getLogger('jenkins_epo')


def loop(wrapped):
    if SETTINGS.LOOP:
        @asyncio.coroutine
        def wrapper(*args, **kwargs):
            while True:
                res = wrapped(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    yield from res

                logger.info("Looping in %s seconds", SETTINGS.LOOP)
                yield from asyncio.sleep(SETTINGS.LOOP)
        functools.update_wrapper(wrapper, wrapped)
        return wrapper
    else:
        return wrapped


class RestartLoop(Exception):
    pass


@asyncio.coroutine
def check_queue(bot):
    if SETTINGS.ALWAYS_QUEUE:
        logger.info("Ignoring queue status. New jobs will be queued.")
        bot.queue_empty = True
        return

    first_check = bot.queue_empty is None
    old, bot.queue_empty = bot.queue_empty, JENKINS.is_queue_empty()
    if not bot.queue_empty:
        yield from asyncio.sleep(5)
        bot.queue_empty = JENKINS.is_queue_empty()
    if old == bot.queue_empty:
        return
    elif bot.queue_empty:
        if first_check:
            logger.warn("Queue is empty. New jobs will be queued.")
        else:
            logger.warn("Queue is empty. Next loop will will queue jobs.")
            raise RestartLoop()
            bot.queue_empty = False
    elif not bot.queue_empty:
        logger.warn("Queue is full. No jobs will be queued.")


@loop
@asyncio.coroutine
def bot():
    """Poll GitHub to find something to do"""
    procedures.whoami()
    bot = Bot(queue_empty=None)

    for repository in procedures.list_repositories(with_settings=True):
        for branch in repository.load_branches():
            try:
                yield from check_queue(bot)
            except RestartLoop:
                if SETTINGS.LOOP:
                    break
            bot.run(branch)

        for pr in repository.load_pulls():
            try:
                yield from check_queue(bot)
            except RestartLoop:
                if SETTINGS.LOOP:
                    break
            try:
                bot.run(pr)
            except Exception:
                if SETTINGS.LOOP:
                    logger.exception("Failed to process %s", pr)
                else:
                    raise

    CACHE.purge()
    CACHE.save()
    logger.info(
        "GitHub poll done. %s remaining API calls.",
        GITHUB.x_ratelimit_remaining,
    )


def list_jobs():
    """List managed jobs"""
    for repository in procedures.list_repositories():
        for job in repository.jobs:
            print(job)


def list_branches():
    """List branches to build"""
    procedures.whoami()
    for repository in procedures.list_repositories(with_settings=True):
        for branch in repository.load_branches():
            print(branch)


def list_pr():
    """List GitHub PR polled"""
    procedures.whoami()
    for repository in procedures.list_repositories(with_settings=True):
        for pr in repository.load_pulls():
            print(pr)


def list_repositories():
    """List GitHub repositories tested by this Jenkins"""
    for repository in procedures.list_repositories():
        print(repository)


def command_exitcode(command_func):
    try:
        command_func()
    except bdb.BdbQuit:
        logger.debug('Graceful exit from debugger')
        return 0
    except Exception:
        logger.exception('Unhandled error')

        if not SETTINGS.DEBUG:
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
    for command in [bot, list_jobs, list_repositories, list_branches, list_pr]:
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
