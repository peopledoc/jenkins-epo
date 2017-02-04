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
from .compat import PriorityQueue
from .settings import SETTINGS
from . import procedures
from .workers import WORKERS


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
    """Poll GitHub to build heads"""
    queue = yield from WORKERS.start()
    yield from procedures.queue_heads(queue)
    while not queue.empty():
        logger.info("Waiting for workers to build heads in queue.")
        yield from queue.join()
    yield from WORKERS.terminate()


def list_extensions():
    """Show bot pipeline of extensions"""
    bot = Bot()
    for extension in bot.extensions:
        print(extension.stage, extension.name)


@asyncio.coroutine
def printer(queue):
    while True:
        head = yield from queue.get()
        print(head)
        queue.task_done()


@asyncio.coroutine
def list_heads():
    """List heads to build"""
    loop = asyncio.get_event_loop()
    queue = PriorityQueue()
    queuer = loop.create_task(procedures.queue_heads(queue))
    printer_ = loop.create_task(printer(queue))

    for _ in range(10):
        if not queue.empty():
            break
        yield from asyncio.sleep(0.5)
    yield from queuer
    yield from queue.join()
    printer_.cancel()


@asyncio.coroutine
def process(url):
    """Process one head"""
    yield from procedures.process_url(url)


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
    for command in bot, list_extensions, list_heads, process:
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
        loop = loop or asyncio.get_event_loop()
        try:
            task = loop.create_task(command_func(**kwargs))
            task.logging_id = command_func.__name__[:4]
            loop.run_until_complete(task)
        except BaseException:
            loop.close()
            raise
        else:
            loop.close()
    else:
        command_func(**kwargs)
