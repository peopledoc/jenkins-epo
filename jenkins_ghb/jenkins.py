import datetime
import fnmatch
import logging
import json
from xml.etree import ElementTree as ET

from jenkinsapi.jenkins import Jenkins
import requests

from .project import Project
from .settings import SETTINGS
from .utils import retry


logger = logging.getLogger(__name__)


class LazyJenkins(object):
    limit_jobs = [p for p in SETTINGS.GHIB_LIMIT_JOBS.split(',') if p]

    def __init__(self):
        self._instance = None

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    @retry()
    def load(self):
        if not self._instance:
            logger.info("Connecting to Jenkins %s", SETTINGS.JENKINS_URL)
            self._instance = Jenkins(SETTINGS.JENKINS_URL)

    def list_projects(self):
        """List github projects tested on this jenkins.

        Mine jobs configs to find github remote URL. Attach each job to the
        corresponding project.

        """

        projects = {}

        for name, job in self.get_jobs():
            if self.limit_jobs:
                for pattern in self.limit_jobs:
                    if fnmatch.fnmatch(name, pattern):
                        break
                else:
                    logger.debug("Skipping %s", name)
                    continue

            job = Job.factory(job)
            for project in job.get_projects():
                logger.info("Managing %s", name)
                project = projects.setdefault(str(project), project)
                project.jobs.append(job)

        return sorted(projects.values(), key=str)

    def is_queue_empty(self):
        return len(self.get_queue().keys()) == 0


JENKINS = LazyJenkins()


class Job(object):
    def __init__(self, api_instance):
        self._instance = api_instance
        self.config = ET.fromstring(self._instance.get_config())

        self.revision_param = None
        xpath_query = './/hudson.plugins.git.BranchSpec/name'
        refspecs = [e.findtext('.') for e in self.config.findall(xpath_query)]
        refspecs = [r for r in refspecs if '$' in r]
        if refspecs:
            for prop in self._instance._data['property']:
                if 'parameterDefinitions' not in prop:
                    continue

                for param in prop['parameterDefinitions']:
                    if [param['name'] in r for r in refspecs]:
                        self.revision_param = param['name']
                        logger.debug(
                            "Using %s param to specify revision for %s",
                            self.revision_param, self
                        )
                        break
                else:
                    logger.warn(
                        "Can't find a parameter for %s", ', '.join(refspecs)
                    )
                break
        else:
            logger.warn("Can't find a parameterized refspec")

    @staticmethod
    def factory(instance):
        if 'activeConfigurations' in instance._data:
            cls = MatrixJob
        else:
            cls = FreestyleJob
        return cls(instance)

    def __getattr__(self, name):
        return getattr(self._instance, name)

    def __str__(self):
        return self._instance.name

    def get_projects(self):
        remote_xpath_query = './/hudson.plugins.git.UserRemoteConfig/url'
        for remote_e in self.config.findall(remote_xpath_query):
            remote_url = remote_e.findtext('.')
            yield Project.from_remote(remote_url)

    def list_not_built_contextes(self, pr, rebuild_failed=None):
        not_built = []
        statuses = pr.get_statuses()
        for context in self.list_contextes():
            status = statuses.get(context, {})
            state = status.get('state')
            # Skip failed job, unless rebuild asked and old
            if state in {'error', 'failure'}:
                failure_date = datetime.datetime.strptime(
                    status['updated_at'], '%Y-%m-%dT%H:%M:%SZ'
                )
                if rebuild_failed and failure_date > rebuild_failed:
                    continue
            # Skip `Backed`, `New` and `Queued` jobs
            elif state == 'pending':
                if status['description'] not in {'Backed', 'New', 'Queued'}:
                    continue
            # Skip other known states
            elif state:
                continue

            not_built.append(context)

        return not_built


class FreestyleJob(Job):
    def list_contextes(self):
        yield self._instance.name

    def build(self, pr, contextes):
        params = {}
        if self.revision_param:
            params[self.revision_param] = pr.ref
        self._instance.invoke(build_params=params)
        logger.info("Triggered new build %s", self)


class MatrixJob(Job):
    def __init__(self, *a, **kw):
        super(MatrixJob, self).__init__(*a, **kw)

        self.configuration_param = None
        for prop in self._instance._data['property']:
            if 'parameterDefinitions' not in prop:
                continue

            for param in prop['parameterDefinitions']:
                if param['type'] == 'MatrixCombinationsParameterDefinition':
                    self.configuration_param = param['name']
                    logger.debug(
                        "Using %s param to select configurations for %s",
                        self.configuration_param, self
                    )

    def list_contextes(self):
        if not self._instance._data['activeConfigurations']:
            raise Exception("No active configuration for %s" % self)

        for c in self._instance._data['activeConfigurations']:
            yield '%s/%s' % (self._instance.name, c['name'])

    def build(self, pr, contextes):
        data = {'parameter': [], 'statusCode': '303', 'redirectTo': '.'}

        if self.revision_param:
            data['parameter'].append({
                'name': self.revision_param,
                'value': pr.ref,
            })

        if self.configuration_param:
            conf_index = len(str(self))+1
            confs = [
                c['name'] for c in self._instance._data['activeConfigurations']
            ]
            not_built = [c[conf_index:] for c in contextes]
            data['parameter'].append({
                'name': self.configuration_param,
                'values': [
                    'true' if c in not_built else 'false'
                    for c in confs
                ],
                'confs': confs,
            })

        res = requests.post(
            self._instance._data['url'] + '/build?delay=0sec',
            data={'json': json.dumps(data)}
        )
        if res.status_code != 200:
            raise Exception('Failed to trigger build.', res)

        for context in contextes:
            logger.info("Triggered new build %s/%s", self, context)
