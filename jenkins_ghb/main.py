import asyncio
import bdb
import logging
import time
import sys

import argh
import requests
from retrying import retry

from .cache import CACHE
from .jenkins import JENKINS
from .pullrequest import GITHUB, loop_pulls
from .settings import SETTINGS


logger = logging.getLogger('jenkins_ghb')


def bot():
    """Poll GitHub to find something to do"""
    for project in JENKINS.list_projects():
        for pr in project.list_pull_requests():
            logger.info("Working on %s", pr)
            triggered_contextes = []
            for job in project.jobs:
                for context in job.list_contextes():
                    try:
                        pr.get_status_for(context)
                        logger.info("%s already triggered", context)
                    except KeyError:
                        logger.info("Trigger new build %s", job)
                        triggered_contextes.extend(job.build(pr))
                        break

            for context in triggered_contextes:
                pr.update_statuses(
                    context=context,
                    description='Queued',
                    state='pending',
                )


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


@retry(stop_max_attempt_number=3, wait_fixed=SETTINGS.WAIT_FIXED)
def get_queue(jenkins):
    data = {}

    queue = jenkins.get_queue()
    # only the keys() method doesn't crash here ..
    queue_items = [queue[i] for i in queue.keys()]

    for item in queue_items:
        params = item.get_parameters()
        if not params:
            # That's not a PR job
            continue

        branch = params.get(SETTINGS.REVISION_PARAM, None)

        if branch is None:
            # That's not a PR job
            continue

        if branch not in data.keys():
            data[branch] = []

        # That might be a matrix configuration name
        item_job_name = item.get_job_name()
        context = item_job_name

        # The above might return a matrix task name, patch it
        for action in item._data.get('actions', []):
            for cause in action.get('causes', []):
                if 'upstreamProject' not in cause.keys():
                    continue

                context = '%s/%s' % (cause['upstreamProject'], item_job_name)
                break

        data[branch].append(context)

    return data


def wait_empty_queue(jenkins, retry_every):
    printed = False
    while len(jenkins.get_queue().keys()) > 0:
        if not printed:
            logger.info('Upstream queue is not empty, waiting')
            printed = True

        time.sleep(float(retry_every))
    logger.info('Upstream queue is free, continuing')


@loop_pulls
def update_github(pr, dry=False):
    """
    Set all missing contexts to pending with description "New" to block the
    merge.
    """

    configuration = pr.get_configuration(GITHUB)
    statuses = pr.get_github_statuses(GITHUB)
    github_contexts = [s['context'] for s in statuses]

    for context in pr.contexts:
        if pr.skip(configuration, context):
            print('Skipping context', context, 'config', configuration)

            if not dry:
                pr.update_context(GITHUB, context, 'success', 'Skipped')

            continue

        if context in github_contexts:
            continue

        print('Missing context:', context)
        if not dry:
            pr.update_context(GITHUB, context, 'pending', 'New')

    for status in statuses:
        if status['context'] in pr.contexts:
            continue

        if status['state'] == 'success':
            continue

        print('Obsolete context:', status['context'])
        if not dry:
            pr.update_context(GITHUB, status['context'], 'success', 'Old')


@loop_pulls
def enqueue_new(pr, wait_free_queue=False, retry_every=10, dry=False):
    """
    Enqueue all "pending" statuses with description "New", set them to
    "Queued".
    """
    if not dry:
        wait_empty_queue(JENKINS, retry_every)

    configuration = pr.get_configuration(GITHUB)
    statuses = pr.get_github_statuses(GITHUB)
    github_contexts = [s['context'] for s in statuses]
    queue = get_queue(JENKINS).get(pr.data['head']['ref'], {})

    build = []
    for context in pr.contexts:
        if context not in github_contexts:
            if pr.skip(configuration, context):
                logger.debug(
                    'Skipping context %s config %r', context, configuration
                )

                if not dry:
                    pr.update_context(GITHUB, context, 'success', 'Skipped')

                continue

            if context in queue:
                continue

            build.append(context)

    for status in statuses:
        if pr.skip(configuration, status['context']):
            continue

        if status['context'] in queue:
            continue

        if status['target_url']:
            continue

        if status['context'] not in pr.contexts and not dry:
            pr.update_context(GITHUB, status['context'], 'success', 'Old')
            continue

        build.append(status['context'])

    if not build:
        logger.debug("Nothing to build")
        return

    if dry:
        logger.debug('Dry-run. Skipping.')
        return

    pr.build(JENKINS, build)

    for context in build:
        pr.update_context(GITHUB, context, 'pending', 'Queued')


def show_queue():
    """
    Just show jenkins queue as other commands would, for debugging.
    """
    print(get_queue(JENKINS))


@loop_pulls
def rebuild_failed(pr, dry=False):
    """
    Inspects console log of failed builds and rebuild if any network failure is
    detected.
    """
    REBUILD = [
        'EOF occurred in violation of protocol',
        'Connection timed out',
        'Read timed out',
        'Unable to receive remote host key',
        'Failed to fetch',
        'Name or service not known',
        'Couldn\'t find any revision to build',
        'failed to download',
        'No space left on device',
        'InsecurePlatformWarning: A true SSLContext object is not available',
    ]

    statuses = pr.get_github_statuses(GITHUB)
    queue = get_queue(JENKINS).get(pr.data['head']['ref'], {})

    @retry(stop_max_attempt_number=3, wait_fixed=SETTINGS.WAIT_FIXED)
    def request_console(status):
        return requests.get(status['target_url'] + 'consoleText')

    build = []
    for status in statuses:
        if status['context'] in queue:
            continue

        if status['state'] not in ('failure', 'error'):
            continue

        response = request_console(status)

        for pattern in REBUILD:
            if pattern not in response.content:
                continue

            build.append(status['context'])
            break

    print('Building failed/errored contexts:', build)

    if dry:
        return

    pr.build(JENKINS, build)


@loop_pulls
def rebuild(pr, contexts='', dry=False):
    """
    Typically for when a job configuration in development has been changed.
    """
    contexts = contexts.split(',')
    statuses = pr.get_github_statuses(GITHUB)
    build = [
        s['context'] for s in statuses
        if (s['state'] != 'success' and s['context'] in contexts)
    ]

    logger.debug('Pending contexts: %r', build)

    if dry:
        logger.debug("Not building")
        return

    pr.build(JENKINS, build)


@loop_pulls
def rebuild_queued(pr, wait_free_queue=False, retry_every=10, dry=False):
    """
    Typically when recovering from a crashed jenkins.
    """

    if wait_free_queue and not dry:
        wait_empty_queue(wait_free_queue, retry_every)

    statuses = pr.get_github_statuses(GITHUB)
    queue = get_queue(JENKINS).get(pr.data['head']['ref'], {})

    build = []
    for status in statuses:
        if status['context'] in queue:
            continue

        if status['state'] == 'pending' and status['description'] == 'Queued':
            build.append(status['context'])

    if not build:
        return

    print('Building contexts:', build)

    if dry:
        return

    pr.build(JENKINS, build)


def reset():
    """Reset jenkins-ghb cache"""
    CACHE.reset()


def run(wait_free_queue=False, retry_every=10, dry=False):
    """Update status and enqueue new"""
    logger.info("Updating github contexts")
    update_github(dry=dry)
    logger.info("Queue new builds")
    enqueue_new(
        wait_free_queue=wait_free_queue, retry_every=retry_every, dry=dry
    )


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
    parser.add_commands([
        bot,
        enqueue_new,
        list_jobs,
        list_projects,
        list_pr,
        rebuild_queued,
        rebuild_failed,
        rebuild,
        reset,
        run,
        show_queue,
        update_github,
    ])

    loop = asyncio.get_event_loop()
    error_handler = ErrorHandler()
    loop.set_exception_handler(error_handler)

    @asyncio.coroutine
    def main_iteration(loop):
        res = parser.dispatch()
        if asyncio.iscoroutine(res):
            res = yield from res

        if SETTINGS.GHIB_LOOP:
            logger.debug("Looping in %s seconds", SETTINGS.GHIB_LOOP)
            loop.call_later(SETTINGS.GHIB_LOOP, main_iteration, loop)
        else:
            loop.stop()

    asyncio.async(main_iteration(loop))
    loop.run_forever()
    loop.close()
    sys.exit(error_handler.exit())
