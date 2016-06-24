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
from .github import ApiError, ApiNotFoundError, GITHUB, cached_request
from .jenkins import JENKINS
from .repository import Branch, PullRequest, Repository
from .settings import SETTINGS
from .utils import match, retry


logger = logging.getLogger('jenkins_ghp')


class Procedures(object):
    pr_filter = [p for p in str(SETTINGS.GHP_PR).split(',') if p]

    @staticmethod
    @retry(wait_fixed=15000)
    def fetch_settings(repository):
        try:
            ghp_yml = GITHUB.fetch_file_contents(repository, '.github/ghp.yml')
            logger.debug("Loading settings from .github/ghp.yml")
        except ApiNotFoundError:
            ghp_yml = None

        collaborators = cached_request(GITHUB.repos(repository).collaborators)
        branches = cached_request(
            GITHUB.repos(repository).branches, protected='true',
        )

        repository.load_settings(
            branches=branches,
            collaborators=collaborators,
            ghp_yml=ghp_yml,
        )

    @staticmethod
    @retry(wait_fixed=15000)
    def list_branches(repository):
        branches = repository.SETTINGS.GHP_BRANCHES
        if not branches:
            logger.debug("No explicit branches configured for %s", repository)
            return []

        for branch in branches:
            logger.debug("Search remote branch %s", branch)
            try:
                ref = cached_request(GITHUB.repos(repository).git(branch))
            except ApiNotFoundError:
                logger.warn("Branch %s not found in %s", branch, repository)
                continue

            sha = ref['object']['sha']
            logger.debug("Fetching commit %s", sha[:7])
            data = cached_request(GITHUB.repos(repository).commits(sha))
            commit = data['commit']
            branch = Branch(repository, ref, commit)
            if branch.is_outdated:
                logger.debug(
                    'Skipping branch %s because older than %s weeks',
                    branch, repository.SETTINGS.GHP_COMMIT_MAX_WEEKS,
                )
                continue
            yield branch

    @classmethod
    @retry(wait_fixed=15000)
    def list_pulls(cls, repository):
        logger.debug("Querying GitHub for %s PR.", repository)
        try:
            pulls = cached_request(GITHUB.repos(repository).pulls)
        except Exception:
            logger.exception("Failed to list PR for %s.", repository)
            return []

        pulls_o = []
        for data in pulls:
            if not match(data['html_url'], cls.pr_filter):
                logger.debug(
                    "Skipping %s (%s).", data['html_url'], data['head']['ref'],
                )
            else:
                pulls_o.append(PullRequest(repository, data))

        for pr in reversed(sorted(pulls_o, key=PullRequest.sort_key)):
            if pr.is_outdated:
                logger.debug(
                    'Skipping PR %s because older than %s weeks.',
                    pr, SETTINGS.GHP_COMMIT_MAX_WEEKS,
                )
            else:
                yield pr

    @classmethod
    def list_repositories(cls, fetch_settings=False):
        repositories = {}
        jobs = JENKINS.get_jobs()

        env_repos = filter(None, SETTINGS.GHP_REPOSITORIES.split(' '))
        for entry in env_repos:
            repository, branches = (entry + ':').split(':', 1)
            owner, name = repository.split('/')
            repositories[repository] = Repository(owner, name)
            logger.debug("Managing %s.", repository)

        for job in jobs:
            for remote in job.get_scm_url():
                repository = Repository.from_remote(remote)
                if repository not in repositories:
                    logger.debug("Managing %s.", repository)
                    repositories[repository] = repository
                else:
                    repository = repositories[repository]

                logger.info("Managing %s.", job)
                repository.jobs.append(job)
                break
            else:
                logger.debug("Skipping %s, no GitHub repository.", job)

        for repo in sorted(repositories.values(), key=str):
            try:
                if fetch_settings:
                    Procedures.fetch_settings(repo)
                yield repo
            except ApiError as e:
                logger.error("Failed to load %s settings: %r", repo, e)

    @staticmethod
    @retry(wait_fixed=15000)
    def whoami():
        user = cached_request(GITHUB.user)
        logger.info("I'm @%s on GitHub.", user['login'])
        return user['login']


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


class RestartLoop(Exception):
    pass


@asyncio.coroutine
def check_queue(bot):
    if SETTINGS.GHP_ALWAYS_QUEUE:
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
    Procedures.whoami()
    bot = Bot(queue_empty=None)

    for repository in Procedures.list_repositories(fetch_settings=True):
        logger.info("Working on %s.", repository)

        for branch in Procedures.list_branches(repository):
            try:
                yield from check_queue(bot)
            except RestartLoop:
                if SETTINGS.GHP_LOOP:
                    break
            bot.run(branch)

        for pr in Procedures.list_pulls(repository):
            try:
                yield from check_queue(bot)
            except RestartLoop:
                if SETTINGS.GHP_LOOP:
                    break
            try:
                bot.run(pr)
            except Exception:
                if SETTINGS.GHP_LOOP:
                    logger.exception("Failed to process %s", pr)
                else:
                    raise

    CACHE.purge()


def list_jobs():
    """List managed jobs"""
    for repository in Procedures.list_repositories():
        for job in repository.jobs:
            print(job)


def list_branches():
    """List branches to build"""
    Procedures.whoami()
    for repository in Procedures.list_repositories(fetch_settings=True):
        logger.info("Working on %s.", repository)
        for branch in Procedures.list_branches(repository):
            print(branch)


def list_pr():
    """List GitHub PR polled"""
    Procedures.whoami()
    for repository in Procedures.list_repositories(fetch_settings=True):
        logger.info("Working on %s.", repository)
        for pr in Procedures.list_pulls(repository):
            print(pr)


def list_repositories():
    """List GitHub repositories tested by this Jenkins"""
    for repository in Procedures.list_repositories():
        print(repository)


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
