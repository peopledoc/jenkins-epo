#!/usr/bin/env python3

import logging
import os
import time

import argh
import requests
from retrying import retry

from .cache import CACHE
from .jenkins import JENKINS
from .pullrequest import GITHUB, REVISION_PARAM, WAIT_FIXED, loop_pulls


logger = logging.getLogger('jenkins-ghb')


@retry(stop_max_attempt_number=3, wait_fixed=WAIT_FIXED)
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

        branch = params.get(REVISION_PARAM, None)

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
            print('Upstream queue is not empty, waiting')
            printed = True

        time.sleep(retry_every)
    print('Upstream queue is free now, continuing')


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
                print('Skipping context', context, 'config', configuration)

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
        return

    print('Building contexts:', build)

    if dry:
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

    @retry(stop_max_attempt_number=3, wait_fixed=WAIT_FIXED)
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

    print('Building contexts:', build)

    if dry:
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


def main():
    parser = argh.ArghParser()
    parser.add_commands([
        enqueue_new,
        rebuild_queued,
        rebuild_failed,
        rebuild,
        reset,
        run,
        show_queue,
        update_github,
    ])

    parser.dispatch()


def entrypoint():
    logging.basicConfig(
        level=logging.WARNING,
        format='[%(name)-16s %(levelname)8s] %(message)s'
    )
    logger.setLevel(logging.DEBUG)
    logger.info("Starting jenkins-ghb")
    retry_after = os.environ.get('RETRY_AFTER', None)

    if retry_after:
        while True:
            main()
            logger.info('Sleeping before starting over')
            time.sleep(int(retry_after))
    else:
        try:
            main()
        except Exception:
            logger.exception('Unhandled error')
            if os.environ.get('PDB', None):
                import pdb
                pdb.post_mortem()
        finally:
            CACHE.save()


if __name__ == '__main__':
    entrypoint()
