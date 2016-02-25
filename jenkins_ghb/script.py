#!/usr/bin/env python3

import functools
import json
import logging
import os
import re
import time

import argh
from github import GitHub, ApiError
import requests
from retrying import retry
import yaml

from .cache import CACHE
from .jenkins import JENKINS


logger = logging.getLogger('jenkins-ghb')


PR = None
GITHUB = None
REVISION_PARAM = os.environ.get('REVISION_PARAM', 'REVISION')
WAIT_FIXED = int(os.environ.get('WAIT_FIXED', 15000))


def loop_pulls(wrapped):
    def wrapper(*args, **kwargs):
        global PR

        for owner_repo, owner, repo, jobs, contexts in generator():
            pulls = GITHUB.repos(owner)(repo).pulls.get(per_page=b'100')

            for pull in pulls:
                logger.info('Doing PR: %s', pull['html_url'])

                # Skip any PR that's not $DEBUG_PR if set
                debug = os.environ.get('DEBUG_PR', None)
                if debug and debug != pull['html_url']:
                    print('Skipping PR', pull['html_url'], 'to debug', debug)
                    continue

                PR = PullRequest(owner, repo, jobs, contexts, pull)
                wrapped(*args, **kwargs)

    functools.update_wrapper(wrapper, wrapped)

    return wrapper


@retry(stop_max_attempt_number=3, wait_fixed=WAIT_FIXED)
def get_expected_contexts(jobs, jenkins):
    cache_key = 'contexts:' + ','.join(jobs)
    contexts = CACHE.get(cache_key, [])

    if contexts:
        return contexts

    for name in jobs:
        job = jenkins.get_job(name)
        configurations = job._data.get('activeConfigurations', [])

        if configurations:
            for c in configurations:
                contexts.append('%s/%s' % (name, c['name']))
        else:
            contexts.append(name)

    CACHE[cache_key] = contexts
    return contexts


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


class PullRequest(object):
    def __init__(self, owner, repo, jobs, contexts, data):
        self.owner = owner
        self.repo = repo
        self.jobs = jobs
        self.contexts = contexts
        self.data = data

    @retry(stop_max_attempt_number=20, wait_fixed=WAIT_FIXED)
    def build(self, jenkins, contexts):
        branch = self.data['head']['ref']

        if not contexts:
            return

        matrix = {}
        for context in contexts:
            if '/' not in context:
                try:
                    jenkins.jobs[context].invoke(
                        build_params={REVISION_PARAM: branch})
                except ValueError:
                    # It worked anyway :D
                    pass

                continue

            job_name, configuration = context.split('/')
            matrix.setdefault(job_name, [])
            matrix[job_name].append(configuration)

        for job_name, configurations in matrix.items():
            job_configurations = [
                '/'.join(c.split('/')[1:])
                for c in self.contexts
                if c.split('/')[0] == job_name
            ]

            data = {
                'parameter': [
                    {
                        'name': REVISION_PARAM,
                        'value': branch,
                    },
                    {
                        'name': 'paramFilter',
                        'values': [
                            'true' if c in configurations else 'false'
                            for c in job_configurations
                        ],
                        'confs': job_configurations,
                    },
                ],
                'statusCode': '303',
                'redirectTo': '.',
            }

            job = JENKINS.get_job(job_name)
            requests.post(job._data['url'] + '/build?delay=0sec', data={
                'Submit': 'Build', 'statusCode': '303',
                'redirectTo': '.', 'json':
                json.dumps(data)})

    @retry(stop_max_attempt_number=20, wait_fixed=WAIT_FIXED)
    def get_github_statuses(self, github):
        url = 'https://api.github.com/repos/%s/%s/status/%s?access_token=%s&per_page=100' % (  # noqa
            self.owner, self.repo, self.data['head']['sha'],
            os.environ['GITHUB_TOKEN'])
        self.statuses = requests.get(url.encode('utf-8')).json()['statuses']
        return self.statuses

    @retry(stop_max_attempt_number=20, wait_fixed=WAIT_FIXED)
    def update_context(self, github, context, state, description, url=None):
        matching = [
            i for (i, d) in enumerate(self.statuses)
            if d['context'] == context
        ]

        if matching:
            current = self.statuses[matching[0]]

            if current['state'] == state:
                logger.info('Already up to date, skipping github api call')
                return  # already up to date

        try:
            (
                github
                .repos(self.owner)(self.repo)
                .statuses(self.data['head']['sha'])
                .post(
                    context=context, state=state, description=description,
                    target_url=url
                )
            )
        except ApiError:  # because we add 1000 updates
            logger.warn('ERROR: 1000 updates on %s', self.data)

    @retry(stop_max_attempt_number=20, wait_fixed=WAIT_FIXED)
    def get_configuration(self, github):
        comments = github.repos(self.owner)(self.repo).issues(
                self.data['number']).comments.get()

        configuration = {}

        for comment in reversed(comments):
            match = re.search('`*.*jenkins:.*`', comment['body'], re.DOTALL)

            if match is None:
                continue

            try:
                configuration = yaml.load(
                    match.group(0).rstrip('`').lstrip('`')
                )['jenkins']
            except:
                pass
            break

        if 'skip' not in configuration.keys():
            configuration['skip'] = None
        elif isinstance(configuration['skip'], basestring):
            configuration['skip'] = [configuration['skip']]
        elif not isinstance(configuration['skip'], list):
            configuration.pop('skip')

        return configuration

    def skip(self, configuration, context):
        if not configuration.get('skip', None):
            return

        for pattern in configuration['skip']:
            if re.match(pattern, context) is not None:
                return True


def get_github():
    return GitHub(
        username=os.environ.get('GITHUB_USERNAME', None),
        access_token=os.environ.get('GITHUB_TOKEN', None) or None,
        password=os.environ.get('GITHUB_PASSWORD', None))


def generator():
    for github_jenkins in os.environ.get('GITHUB_JOBS').split(' '):
        owner_repo, jobs_config = github_jenkins.split(':')
        owner, repo = owner_repo.split('/')
        jobs = jobs_config.split(',')
        logger.debug("Managing jobs %s for repo %s", jobs, owner_repo)
        contexts = get_expected_contexts(jobs, JENKINS)

        yield owner_repo, owner, repo, jobs, contexts


def wait_empty_queue(jenkins, retry_every):
    printed = False
    while len(jenkins.get_queue().keys()) > 0:
        if not printed:
            print('Upstream queue is not empty, waiting')
            printed = True

        time.sleep(retry_every)
    print('Upstream queue is free now, continuing')


@loop_pulls
def update_github(dry=False):
    """
    Set all missing contexts to pending with description "New" to block the
    merge.
    """

    configuration = PR.get_configuration(GITHUB)
    statuses = PR.get_github_statuses(GITHUB)
    github_contexts = [s['context'] for s in statuses]

    for context in PR.contexts:
        if PR.skip(configuration, context):
            print('Skipping context', context, 'config', configuration)

            if not dry:
                PR.update_context(GITHUB, context, 'success', 'Skipped')

            continue

        if context in github_contexts:
            continue

        print('Missing context:', context)
        if not dry:
            PR.update_context(GITHUB, context, 'pending', 'New')

    for status in statuses:
        if status['context'] in PR.contexts:
            continue

        if status['state'] == 'success':
            continue

        print('Obsolete context:', status['context'])
        if not dry:
            PR.update_context(GITHUB, status['context'], 'success', 'Old')


@loop_pulls
def enqueue_new(wait_free_queue=False, retry_every=10, dry=False):
    """
    Enqueue all "pending" statuses with description "New", set them to
    "Queued".
    """
    if not dry:
        wait_empty_queue(JENKINS, retry_every)

    configuration = PR.get_configuration(GITHUB)
    statuses = PR.get_github_statuses(GITHUB)
    github_contexts = [s['context'] for s in statuses]
    queue = get_queue(JENKINS).get(PR.data['head']['ref'], {})

    build = []
    for context in PR.contexts:
        if context not in github_contexts:
            if PR.skip(configuration, context):
                print('Skipping context', context, 'config', configuration)

                if not dry:
                    PR.update_context(GITHUB, context, 'success', 'Skipped')

                continue

            if context in queue:
                continue

            build.append(context)

    for status in statuses:
        if PR.skip(configuration, status['context']):
            continue

        if status['context'] in queue:
            continue

        if status['target_url']:
            continue

        if status['context'] not in PR.contexts and not dry:
            PR.update_context(GITHUB, status['context'], 'success', 'Old')
            continue

        build.append(status['context'])

    if not build:
        return

    print('Building contexts:', build)

    if dry:
        return

    PR.build(JENKINS, build)

    for context in build:
        PR.update_context(GITHUB, context, 'pending', 'Queued')


def show_queue():
    """
    Just show jenkins queue as other commands would, for debugging.
    """
    print(get_queue(JENKINS))


@loop_pulls
def rebuild_failed(dry=False):
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

    statuses = PR.get_github_statuses(GITHUB)
    queue = get_queue(JENKINS).get(PR.data['head']['ref'], {})

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

    PR.build(JENKINS, build)


@loop_pulls
def rebuild(contexts='', dry=False):
    """
    Typically for when a job configuration in development has been changed.
    """
    contexts = contexts.split(',')
    statuses = PR.get_github_statuses(GITHUB)
    build = [
        s['context'] for s in statuses
        if (s['state'] != 'success' and s['context'] in contexts)
    ]

    print('Building contexts:', build)

    if dry:
        return

    PR.build(JENKINS, build)


@loop_pulls
def rebuild_queued(wait_free_queue=False, retry_every=10, dry=False):
    """
    Typically when recovering from a crashed jenkins.
    """

    if wait_free_queue and not dry:
        wait_empty_queue(wait_free_queue, retry_every)

    statuses = PR.get_github_statuses(GITHUB)
    queue = get_queue(JENKINS).get(PR.data['head']['ref'], {})

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

    PR.build(JENKINS, build)


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
    global GITHUB

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

    GITHUB = get_github()

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
