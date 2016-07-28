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

import logging
import json
import re

from jenkinsapi.build import Build
from jenkinsapi.jenkins import Jenkins
from jenkinsapi.custom_exceptions import UnknownJob
from jenkins_yml import Job as JobSpec
import requests

from .settings import SETTINGS
from .utils import match, retry


logger = logging.getLogger(__name__)


class LazyJenkins(object):
    build_url_re = re.compile(r'.*/job/(?P<job>.*?)/.*(?P<buildno>\d+)/?')

    def __init__(self):
        self._instance = None

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    @retry
    def get_build_from_url(self, url):
        if not url.startswith(self.baseurl):
            raise Exception("%s is not on this Jenkins" % url)
        match = self.build_url_re.match(url)
        if not match:
            raise Exception("Failed to parse build URL %s" % url)
        job_name = match.group('job')
        job = self.get_job(job_name)
        buildno = int(match.group('buildno'))
        try:
            return Build(url, buildno, job)
        except requests.exceptions.HTTPError as e:
            if 404 == e.response.status_code:
                raise Exception("Build %s not found. Lost ?" % url)
            raise

    @retry
    def load(self):
        if not self._instance:
            logger.info("Connecting to Jenkins %s", SETTINGS.JENKINS_URL)
            self._instance = Jenkins(SETTINGS.JENKINS_URL)

    @retry
    def get_jobs(self):
        self.load()
        if not SETTINGS.GHP_JOBS_AUTO and not self.jobs_filter:
            logger.warn("Use GHP_JOBS env var to list jobs to managed.")
            return []

        for name, job in self._instance.get_jobs():
            job = Job.factory(job)
            if job.managed:
                yield job

    @retry
    def is_queue_empty(self):
        return len(self.get_queue().keys()) == 0

    @retry
    def create_job(self, job_spec):
        try:
            api_instance = self._instance.get_job(job_spec.name)
        except UnknownJob:
            config = job_spec.as_xml()
            if SETTINGS.GHP_DRY_RUN:
                logger.info("Would create new Jenkins job %s.", job_spec)
                return None

            api_instance = self._instance.create_job(job_spec.name, config)
            logger.warning("Created new Jenkins job %s.", job_spec.name)
        else:
            logger.debug("Not updating existing job %s.", job_spec.name)

        return Job.factory(api_instance)


JENKINS = LazyJenkins()


class Job(object):
    jobs_filter = [p for p in SETTINGS.GHP_JOBS.split(',') if p]

    @staticmethod
    def factory(instance):
        if 'activeConfigurations' in instance._data:
            cls = MatrixJob
        else:
            cls = FreestyleJob
        return cls(instance)

    def __init__(self, api_instance):
        self._instance = api_instance
        self.config = self._instance._get_config_element_tree()
        self.spec = JobSpec.from_xml(self.name, self.config)

        xpath_query = './/triggers/com.cloudbees.jenkins.GitHubPushTrigger'
        self.push_trigger = bool(self.config.findall(xpath_query))
        xpath_query = './/triggers/hudson.triggers.SCMTrigger'
        self.polled_by_jenkins = bool(self.config.findall(xpath_query))

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.name)

    def __str__(self):
        return self._instance.name

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __getattr__(self, name):
        return getattr(self._instance, name)

    @property
    def managed(self):
        if not match(self.name, self.jobs_filter):
            logger.debug("%s filtered.", self)
            return False

        if not self.is_enabled():
            logger.debug("%s disabled.", self)
            return False

        if SETTINGS.GHP_JOBS_AUTO and self.polled_by_jenkins:
            logger.debug("%s is polled by Jenkins.", self)
            return False

        # This option works only with webhook, so we can safely use it to
        # mark a job for jenkins-ghp.
        if SETTINGS.GHP_JOBS_AUTO and not self.push_trigger:
            logger.debug("Trigger on push disabled on %s.", self)
            return False

        return True

    @property
    def revision_param(self):
        if not hasattr(self, '_revision_param'):
            self._revision_param = None
            xpath_query = './/hudson.plugins.git.BranchSpec/name'
            refspecs = [
                e.findtext('.') for e in self.config.findall(xpath_query)
            ]
            refspecs = [r for r in refspecs if '$' in r]
            if refspecs:
                for prop in self._instance._data['property']:
                    if 'parameterDefinitions' not in prop:
                        continue

                    for param in prop['parameterDefinitions']:
                        if sum([param['name'] in r for r in refspecs]):
                            self._revision_param = param['name']
                            logger.debug(
                                "Using %s param to specify revision for %s",
                                self._revision_param, self
                            )
                            break
                    else:
                        logger.warn(
                            "Can't find a parameter for %s",
                            ', '.join(refspecs)
                        )
                    break
            else:
                logger.warn("Can't find a revision param in %s", self)

        return self._revision_param


class FreestyleJob(Job):
    def list_contexts(self):
        yield self._instance.name

    def build(self, pr, spec, contexts):
        log = str(self)
        params = spec.config['parameters'].copy()
        if self.revision_param:
            params[self.revision_param] = pr.ref
            log += ' for %s' % pr.ref

        if SETTINGS.GHP_DRY_RUN:
            return logger.info("Would queue %s", log)

        self._instance.invoke(build_params=params, delay=0, cause='GHP')
        logger.info("Queued new build %s", log)


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

    def list_contexts(self):
        if not self._instance._data['activeConfigurations']:
            raise Exception("No active configuration for %s" % self)

        for c in self._instance._data['activeConfigurations']:
            yield '%s/%s' % (self._instance.name, c['name'])

    def build(self, pr, spec, contexts):
        data = {'parameter': [], 'statusCode': '303', 'redirectTo': '.'}

        for name, value in spec.config['parameters'].items():
            data['parameter'].append({'name': name, 'value': value})

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
            not_built = [c[conf_index:] for c in contexts]
            data['parameter'].append({
                'name': self.configuration_param,
                'values': [
                    'true' if c in not_built else 'false'
                    for c in confs
                ],
                'confs': confs,
            })

        if SETTINGS.GHP_DRY_RUN:
            for context in contexts:
                logger.info("Would trigger %s for %s", context, pr.ref)
            return

        res = requests.post(
            self._instance._data['url'] + '/build?delay=0sec&cause=GHP',
            data={'json': json.dumps(data)}
        )
        if res.status_code != 200:
            raise Exception('Failed to trigger build.', res)

        for context in contexts:
            log = '%s/%s' % (self, context)
            if self.revision_param:
                log += ' for %s' % pr.ref
            logger.info("Triggered new build %s", log)
