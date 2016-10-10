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

from datetime import datetime
from itertools import product
import logging
import json
import re

from jenkinsapi.build import Build
from jenkinsapi.jenkins import Jenkins
from jenkins_yml import Job as JobSpec
import requests
import yaml

from .settings import SETTINGS
from .utils import parse_patterns, retry


logger = logging.getLogger(__name__)


class LazyJenkins(object):
    build_url_re = re.compile(r'.*/job/(?P<job>.*?)/.*(?P<buildno>\d+)/?')

    def __init__(self, instance=None):
        self._instance = instance

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
    def is_queue_empty(self):
        logging.debug("GET %s queue.", SETTINGS.JENKINS_URL)
        data = self.get_queue()._data
        items = filter(lambda i: not i['stuck'], data['items'])
        return len(list(items)) == 0

    @retry
    def get_job(self, name):
        self.load()
        return Job.factory(self._instance.get_job(name))

    DESCRIPTION_TMPL = """\
%(description)s

<!--
%(embedded_data)s
-->
"""

    def preprocess_spec(self, spec):
        embedded_data = dict(updated_at=datetime.now())
        spec.config['description'] = self.DESCRIPTION_TMPL % dict(
            description=re.sub(
                r"\s*(<!--\nepo:.*-->)", "",
                spec.config.get('description', ''),
                flags=re.S,
            ),
            embedded_data=yaml.dump(dict(epo=embedded_data)).strip(),
        )
        return spec

    @retry
    def create_job(self, job_spec):
        job_spec = self.preprocess_spec(job_spec)
        config = job_spec.as_xml()
        if SETTINGS.DRY_RUN:
            logger.warn("Would create new Jenkins job %s.", job_spec)
            return None

        api_instance = self._instance.create_job(job_spec.name, config)
        logger.warn("Created new Jenkins job %s.", job_spec.name)

        return Job.factory(api_instance)

    @retry
    def update_job(self, job_spec):
        api_instance = self._instance.get_job(job_spec.name)
        job_spec = self.preprocess_spec(job_spec)
        config = job_spec.as_xml()
        if SETTINGS.DRY_RUN:
            logger.warn("Would update Jenkins job %s.", job_spec)
            return Job.factory(api_instance)

        api_instance.update_config(config)
        logger.warn("Updated Jenkins job %s.", job_spec.name)

        return Job.factory(api_instance)


JENKINS = LazyJenkins()


class Job(object):
    jobs_filter = parse_patterns(SETTINGS.JOBS)
    embedded_data_re = re.compile(
        r'^(?P<yaml>epo:.*)(?=^[^ ])', re.MULTILINE | re.DOTALL,
    )

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
        match = self.embedded_data_re.search(
            self._instance._data.get('description', '')
        )
        data = match.group('yaml') if match else '{}'
        self.embedded_data = yaml.load(data).get('epo', {})

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

    @property
    def updated_at(self):
        return self.embedded_data.get('updated_at')

    @property
    def node_param(self):
        if not hasattr(self, '_node_param'):
            self._node_param = None
            for param in self.get_params():
                if param['type'] != 'LabelParameterDefinition':
                    continue

                self._node_param = param['name']
                logger.debug(
                    "Using %s param to target node for %s.",
                    self._node_param, self,
                )
                break
        return self._node_param


class FreestyleJob(Job):
    def list_contexts(self, spec):
        yield self._instance.name

    def build(self, pr, spec, contexts):
        log = str(self)
        params = spec.config.get('parameters', {}).copy()
        if self.revision_param:
            params[self.revision_param] = pr.ref
            log += ' for %s' % pr.ref

        if 'node' in spec.config:
            if self.node_param:
                params[self.node_param] = spec.config['node']
            else:
                logger.warn(
                    "Can't assign build to node %s.", spec.config['node'],
                )

        if SETTINGS.DRY_RUN:
            return logger.info("Would queue %s.", log)

        self._instance.invoke(build_params=params, delay=0, cause='EPO')
        logger.info("Queued new build %s", log)


class MatrixJob(Job):
    @property
    def combination_param(self):
        if not hasattr(self, '_combination_param'):
            self._combination_param = None
            for param in self._instance.get_params():
                if param['type'] != 'MatrixCombinationsParameterDefinition':
                    continue

                self._combination_param = param['name']
                logger.debug(
                    "Using %s param to select combinations for %s.",
                    self._combination_param, self
                )
        return self._combination_param

    @property
    def node_axis(self):
        if not hasattr(self, '_node_axis'):
            self._node_axis = None
            xpath = './/axes/hudson.matrix.LabelAxis/name'
            elements = self.config.findall(xpath)
            if elements:
                self._node_axis = elements[0].text
                logger.debug(
                    "Using %s axis to select node for %s.",
                    self._node_axis, self,
                )

        return self._node_axis

    def list_contexts(self, spec):
        axis = []
        if self.node_axis:
            if 'node' in spec.config:
                node = spec.config['node']
            else:
                node = sorted(spec.config['merged_nodes'])[0]

            axis.append(['%s=%s' % (self.node_axis, node)])

        for name, values in spec.config['axis'].items():
            axis.append(['%s=%s' % (name, v) for v in sorted(values)])

        for name, values in self.spec.config['axis'].items():
            if name in spec.config['axis']:
                continue
            axis.append(['%s=%s' % (name, values[0])])

        combinations = [','.join(sorted(a)) for a in product(*axis)]
        active_combinations = [
            c['name']
            for c in self._instance._data['activeConfigurations']
        ]

        for name in combinations:
            if name not in active_combinations:
                logger.debug("%s not active in Jenkins. Skipping.", name)
                continue

            yield '%s/%s' % (self._instance.name, name)

    def build(self, pr, spec, contexts):
        data = {'parameter': [], 'statusCode': '303', 'redirectTo': '.'}

        for name, value in spec.config.get('parameters', {}).items():
            data['parameter'].append({'name': name, 'value': value})

        if self.revision_param:
            data['parameter'].append({
                'name': self.revision_param,
                'value': pr.ref,
            })

        if self.combination_param:
            conf_index = len(str(self))+1
            confs = [
                c['name']
                for c in self._instance._data.get('activeConfigurations', [])
            ]
            not_built = [c[conf_index:] for c in contexts]
            data['parameter'].append({
                'name': self.combination_param,
                'values': [
                    'true' if c in not_built else 'false'
                    for c in confs
                ],
                'confs': confs,
            })

        if SETTINGS.DRY_RUN:
            for context in contexts:
                logger.info("Would trigger %s for %s", context, pr.ref)
            return

        res = requests.post(
            self._instance._data['url'] + '/build?delay=0sec&cause=Bot',
            data={'json': json.dumps(data)}
        )
        if res.status_code != 200:
            raise Exception('Failed to trigger build.', res)

        for context in contexts:
            log = '%s/%s' % (self, context)
            if self.revision_param:
                log += ' for %s' % pr.ref
            logger.info("Triggered new build %s", log)
