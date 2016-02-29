import argparse
import asyncio
import bdb
import functools
import inspect
import logging
import sys

from .bot import Bot
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


@loop
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


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND')
    for command in [bot, list_jobs, list_projects, list_pr]:
        subparser = subparsers.add_parser(
            command.__name__.replace('_', '-'),
            help=inspect.cleandoc(command.__doc__ or '').split('\n')[0],
        )
        subparser.set_defaults(command_func=command)

    args = parser.parse_args()
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
                task.exception()  # Consume task exception
                raise
            finally:
                loop.close()

        sys.exit(command_exitcode(run_async))
    else:
        sys.exit(command_exitcode(command_func))
