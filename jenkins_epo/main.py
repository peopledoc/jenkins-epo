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
import inspect
import logging
import sys

from aiohttp.web import run_app

from .bot import Bot
from . import procedures
from .settings import SETTINGS
from .web import app as webapp, register_webhook
from .workers import WORKERS


logger = logging.getLogger('jenkins_epo')

COMMANDS = []


def command(callable_):
    COMMANDS.append(callable_)
    return callable_


@command
def bot():
    """Poll GitHub to build heads"""
    loop = asyncio.get_event_loop()
    loop.create_task(WORKERS.start())
    if SETTINGS.POLL_INTERVAL:
        loop.create_task(procedures.poll())

    run_app(
        webapp,
        host=SETTINGS.HOST,
        port=SETTINGS.PORT,
    )


@command
def list_extensions():
    """Show bot pipeline of extensions"""
    bot = Bot()
    for extension in bot.extensions:
        print(extension.stage, extension.name)


@command
@asyncio.coroutine
def list_heads():
    """List heads to build"""
    yield from WORKERS.start()
    yield from procedures.print_heads()
    yield from WORKERS.terminate()


@command
def list_plugins():
    """List required Jenkins plugins"""
    from jenkins_yml.job import Job
    for plugin in sorted(Job.required_plugins):
        print(plugin)


@command
@asyncio.coroutine
def process(url):
    """Process one head"""
    yield from procedures.whoami()
    yield from procedures.process_url(url, throttle=False)


@command
@asyncio.coroutine
def register():
    """Register GitHub webhook"""
    if not SETTINGS.GITHUB_SECRET:
        logger.error("Use GITHUB_SECRET to define webhook shared secret.")
        sys.exit(1)

    yield from WORKERS.start()
    yield from register_webhook()
    yield from WORKERS.terminate()


def resolve(func):
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func


def add_command_parser(subparsers, command):
    parser = subparsers.add_parser(
        command.__name__.replace('_', '-'),
        help=inspect.cleandoc(command.__doc__ or '').split('\n')[0],
    )
    parser.set_defaults(command_func=command)
    code = resolve(command).__code__
    argnames = code.co_varnames[:code.co_argcount]
    for var in argnames:
        logger.debug("Add %s argument", var.upper())
        parser.add_argument(
            var, metavar=var.upper(), type=str,
        )


def main(argv=None, *, loop=None):
    argv = argv or sys.argv
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND')
    for command in COMMANDS:
        add_command_parser(subparsers, command)

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
            task.result()
        else:
            loop.close()
    else:
        command_func(**kwargs)
