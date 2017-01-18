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
from concurrent.futures import CancelledError
import functools
import inspect
import logging
import sys


from .bot import Bot
from .cache import CACHE
from .github import GITHUB
from .repository import UnauthorizedRepository
from .settings import SETTINGS
from .utils import grouper
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


@asyncio.coroutine
def process_head(head):
    task = asyncio.Task.current_task()
    task.logging_id = head.sha[:4]
    bot = Bot()
    try:
        head.repository.load_settings()
    except UnauthorizedRepository:
        logger.error("Write access denied to %s.", head.repository)
        raise
    except Exception:
        logger.exception("Failed to load %s settings.", head.repository)
        raise

    logger.info("Working on %s.", head)
    try:
        yield from bot.run(head)
    except CancelledError:
        logger.warn("Cancelled processing %s:", head)
    except Exception as e:
        logger.error("Failed to process %s: %r", head, e)
        if SETTINGS.DEBUG:
            raise

    logger.info("Processed %s.", head)
    del task.logging_id


@loop
@asyncio.coroutine
def bot():
    """Poll GitHub to find something to do"""
    task = asyncio.Task.current_task()
    task.logging_id = 'bot'
    yield from procedures.whoami()
    loop = asyncio.get_event_loop()

    failures = []
    return_exceptions = SETTINGS.LOOP or not SETTINGS.DEBUG
    for chunk in grouper(procedures.iter_heads(), SETTINGS.CONCURRENCY):
        yield from procedures.throttle_github()
        tasks = [
            loop.create_task(process_head(head))
            for head in chunk if head
        ]

        res = yield from asyncio.gather(
            *tasks, return_exceptions=return_exceptions
        )
        failures.extend([r for r in res if isinstance(r, Exception)])

    CACHE.purge()
    CACHE.save()
    logger.info(
        "GitHub poll done. %s remaining API calls.",
        GITHUB.x_ratelimit_remaining,
    )

    if failures:
        if not SETTINGS.LOOP:
            raise Exception("Some heads failed to process.")


def list_extensions():
    bot = Bot()
    for extension in bot.extensions:
        print(extension.stage, extension.name)


@asyncio.coroutine
def list_heads():
    """List heads to build"""
    yield from procedures.whoami()
    for head in procedures.iter_heads():
        print(head)


def command_exitcode(command_func):
    try:
        command_func()
    except bdb.BdbQuit:
        logger.debug('Graceful exit from debugger')
        return 0
    except (Exception, KeyboardInterrupt):
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
    for command in [bot, list_extensions, list_heads]:
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
