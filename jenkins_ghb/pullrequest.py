import functools
import json
import logging
import re
import yaml

from github import GitHub, ApiError
import requests
from retrying import retry

from .cache import CACHE
from .jenkins import JENKINS
from .settings import SETTINGS


logger = logging.getLogger(__name__)


def generator():
    for github_jenkins in SETTINGS.GITHUB_JOBS.split(' '):
        owner_repo, jobs_config = github_jenkins.split(':')
        owner, repo = owner_repo.split('/')
        jobs = jobs_config.split(',')
        logger.debug("Managing jobs %s for repo %s", jobs, owner_repo)
        contexts = get_expected_contexts(jobs, JENKINS)

        yield owner_repo, owner, repo, jobs, contexts


@retry(stop_max_attempt_number=3, wait_fixed=SETTINGS.WAIT_FIXED)
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


def loop_pulls(wrapped):
    def wrapper(*args, **kwargs):
        for owner_repo, owner, repo, jobs, contexts in generator():
            pulls = GITHUB.repos(owner)(repo).pulls.get(per_page=b'100')

            for pull in pulls:
                logger.info('Doing PR: %s', pull['html_url'])

                # Skip any PR that's not $DEBUG_PR if set
                debug = SETTINGS.DEBUG_PR
                if debug and debug != pull['html_url']:
                    print('Skipping PR', pull['html_url'], 'to debug', debug)
                    continue

                pr = PullRequest(owner, repo, jobs, contexts, pull)
                wrapped(pr=pr, *args, **kwargs)

    functools.update_wrapper(wrapper, wrapped)

    return wrapper


class PullRequest(object):
    def __init__(self, owner, repo, jobs, contexts, data):
        self.owner = owner
        self.repo = repo
        self.jobs = jobs
        self.contexts = contexts
        self.data = data

    @retry(stop_max_attempt_number=20, wait_fixed=SETTINGS.WAIT_FIXED)
    def build(self, jenkins, contexts):
        branch = self.data['head']['ref']

        if not contexts:
            return

        matrix = {}
        for context in contexts:
            if '/' not in context:
                try:
                    jenkins.jobs[context].invoke(
                        build_params={SETTINGS.REVISION_PARAM: branch})
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
                        'name': SETTINGS.REVISION_PARAM,
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

    @retry(stop_max_attempt_number=20, wait_fixed=SETTINGS.WAIT_FIXED)
    def get_github_statuses(self, github):
        url = 'https://api.github.com/repos/%s/%s/status/%s?access_token=%s&per_page=100' % (  # noqa
            self.owner, self.repo, self.data['head']['sha'],
            SETTINGS.GITHUB_TOKEN)
        self.statuses = requests.get(url.encode('utf-8')).json()['statuses']
        return self.statuses

    @retry(stop_max_attempt_number=20, wait_fixed=SETTINGS.WAIT_FIXED)
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

    @retry(stop_max_attempt_number=20, wait_fixed=SETTINGS.WAIT_FIXED)
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


class LazyGithub(object):
    def __init__(self):
        self._instance = None

    def load(self):
        if not self._instance:
            self._instance = GitHub(
                username=SETTINGS.GITHUB_USERNAME,
                access_token=SETTINGS.GITHUB_TOKEN or None,
                password=SETTINGS.GITHUB_PASSWORD,
            )

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)


GITHUB = LazyGithub()
