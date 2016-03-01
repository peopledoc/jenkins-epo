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
from xml.etree import ElementTree as ET

from jenkinsapi.build import Build
from jenkinsapi.jenkins import Jenkins
import requests

from .project import Project
from .settings import SETTINGS
from .utils import match, retry


logger = logging.getLogger(__name__)


class LazyJenkins(object):
    jobs_filter = [p for p in SETTINGS.GHP_JOBS.split(',') if p]
    projects_filter = [p for p in SETTINGS.GHP_PROJECTS.split(',') if p]
    build_url_re = re.compile(r'.*/job/(?P<job>.*?)/.*(?P<buildno>\d+)/?')

    def __init__(self):
        self._instance = None

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    @retry()
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
            if not match(name, self.jobs_filter):
                logger.debug("Skipping %s", name)
                continue

            job = Job.factory(job)
            if job.polled_by_jenkins:
                logger.debug("Skipping %s, polled by Jenkins", name)
                continue

            # This option works only with webhook, so we can safely use it to
            # mark a job for jenkins-ghp.
            if not job.push_trigger:
                logger.debug("Skipping %s, trigger on push disabled", name)
                continue

            for project in job.get_projects():
                if not match(str(project), self.projects_filter):
                    logger.debug("Skipping %s", project)
                    continue

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

        xpath_query = './/triggers/com.cloudbees.jenkins.GitHubPushTrigger'
        self.push_trigger = bool(self.config.findall(xpath_query))
        xpath_query = './/triggers/hudson.triggers.SCMTrigger'
        self.polled_by_jenkins = bool(self.config.findall(xpath_query))

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
                        if [param['name'] in r for r in refspecs]:
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


class FreestyleJob(Job):
    def list_contexts(self):
        yield self._instance.name

    def build(self, pr, contexts):
        params = {}
        if self.revision_param:
            params[self.revision_param] = pr.ref

        if SETTINGS.GHP_DRY_RUN:
            return logger.info("Would trigger %s", self)

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

    def list_contexts(self):
        if not self._instance._data['activeConfigurations']:
            raise Exception("No active configuration for %s" % self)

        for c in self._instance._data['activeConfigurations']:
            yield '%s/%s' % (self._instance.name, c['name'])

    def build(self, pr, contexts):
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
                logger.info("Would trigger %s", context)
            return

        res = requests.post(
            self._instance._data['url'] + '/build?delay=0sec',
            data={'json': json.dumps(data)}
        )
        if res.status_code != 200:
            raise Exception('Failed to trigger build.', res)

        for context in contexts:
            logger.info("Triggered new build %s/%s", self, context)
