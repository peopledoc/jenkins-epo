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
# This file provides all jenkins-epo CLI interaction : commands, arguments,
# etc. and manage asyncio loop.

import argparse
import asyncio
import functools
import inspect
import logging
import sys


from .bot import Bot
from .cache import CACHE
from .github import GITHUB
from .settings import SETTINGS
from .utils import grouper
from .watchdog import WatchDog
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


@loop
@asyncio.coroutine
def bot():
    """Poll GitHub to find something to do"""
    task = asyncio.Task.current_task()
    task.logging_id = 'bot'
    me = yield from procedures.whoami()
    loop = asyncio.get_event_loop()

    failures = []
    return_exceptions = SETTINGS.LOOP or not SETTINGS.DEBUG
    for chunk in grouper(procedures.iter_heads(), SETTINGS.CONCURRENCY):
        yield from procedures.throttle_github()
        tasks = [
            loop.create_task(procedures.process_head(head, me=me))
            for head in chunk if head
        ]

        res = yield from asyncio.gather(
            *tasks, return_exceptions=return_exceptions
        )
        failures.extend([r for r in res if isinstance(r, Exception)])

    CACHE.purge()

    logger.info(
        "GitHub poll done. %s remaining API calls.",
        GITHUB.x_ratelimit_remaining,
    )

    if failures:
        if not SETTINGS.LOOP:
            raise Exception("Some heads failed to process.")


def list_extensions():
    """Show bot pipeline of extensions"""
    bot = Bot()
    for extension in bot.extensions:
        print(extension.stage, extension.name)


@asyncio.coroutine
def list_heads():
    """List heads to build"""
    yield from procedures.whoami()
    for head in procedures.iter_heads():
        print(head)


@asyncio.coroutine
def run_async(command_func, *args, **kwargs):
    me = asyncio.Task.current_task()
    try:
        yield from command_func(*args, **kwargs)
    except BaseException:
        # Hide ^C in terminal
        sys.stderr.write('\r')
        for task in asyncio.Task.all_tasks():
            if task is me:
                continue

            if task.done():
                # Consume any exception
                task.exception()
            else:
                logger.debug("Cancelling %s", task)
                task.cancel()
        CACHE.save()
        raise


def addcommand(subparsers, command):
    parser = subparsers.add_parser(
        command.__name__.replace('_', '-'),
        help=inspect.cleandoc(command.__doc__ or '').split('\n')[0],
    )
    parser.set_defaults(command_func=command)
    argnames = command.__code__.co_varnames[:command.__code__.co_argcount]
    for var in argnames:
        parser.add_argument(
            var, metavar=var.upper(), type=str
        )


def main(argv=None, *, loop=None):
    argv = argv or sys.argv
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND')
    for command in bot, list_extensions, list_heads:
        addcommand(subparsers, command)

    args = parser.parse_args(argv)
    try:
        command_func = args.command_func
    except AttributeError:
        command_func = parser.print_usage

    kwargs = {
        k: v
        for k, v in args._get_kwargs()
        if k not in {'command', 'command_func'}
    }

    if asyncio.iscoroutinefunction(command_func):
        WatchDog().run(run_async, command_func, **kwargs)
    else:
        command_func(**kwargs)
