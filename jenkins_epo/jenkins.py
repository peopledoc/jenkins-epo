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


import ast
import asyncio
from datetime import datetime, timedelta
from itertools import product
import logging
import re

import aiohttp
from jenkinsapi.jenkinsbase import JenkinsBase
from jenkinsapi.jenkins import Jenkins, Requester
from jenkins_yml import Job as JobSpec
import yaml
from yarl import URL

from .settings import SETTINGS
from .utils import format_duration, match, parse_patterns, retry
from .web import fullurl


logger = logging.getLogger(__name__)


class NotOnJenkins(Exception):
    pass


class RESTClient(object):
    def __init__(self, path=''):
        self.path = path

    def __call__(self, arg):
        return self.__class__(self.path.rstrip('/') + '/' + str(arg))

    def __getattr__(self, name):
        return self(name)

    @retry
    def afetch(self, **kw):
        session = aiohttp.ClientSession()
        url = URL(self.path)
        if kw:
            url = url.with_query(**kw)
        logger.debug("GET %s", url)
        try:
            response = yield from session.get(url, timeout=10)
            payload = yield from response.read()
        finally:
            yield from session.close()
        response.raise_for_status()
        return payload.decode('utf-8')

    def aget(self, **kw):
        payload = yield from self.api.python.afetch(**kw)
        return ast.literal_eval(payload)

    @retry
    def apost(self, **kw):
        session = aiohttp.ClientSession()
        url = URL(self.path)
        if kw:
            url = url.with_query(**kw)
        logger.debug("POST %s", url)
        try:
            response = yield from session.post(url, timeout=10)
            payload = yield from response.read()
        finally:
            yield from session.close()
        response.raise_for_status()
        return payload.decode('utf-8')


class VerboseRequester(Requester):
    def get_url(self, url, *a, **kw):
        logger.debug("GET %s (sync)", url)
        return super(VerboseRequester, self).get_url(url, *a, **kw)


# Monkey patch poll=True to avoid I/O in __init__
JenkinsBase.__init__.__defaults__ = (False,)


class LazyJenkins(object):
    queue_patterns = parse_patterns(SETTINGS.JENKINS_QUEUE)

    def __init__(self, instance=None):
        self._instance = instance
        self.rest = None

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    @retry
    def load(self):
        if not self._instance:
            logger.debug("Connecting to Jenkins %s", SETTINGS.JENKINS_URL)
            self.rest = RESTClient(SETTINGS.JENKINS_URL)
            self._instance = Jenkins(
                baseurl=SETTINGS.JENKINS_URL,
                requester=VerboseRequester(baseurl=SETTINGS.JENKINS_URL),
                lazy=True,
            )

    @asyncio.coroutine
    def is_queue_empty(self):
        payload = yield from self.rest.queue.aget()
        items = [
            i for i in payload['items']
            if not i['stuck'] and match(i['task']['name'], self.queue_patterns)
        ]
        return len(items) <= SETTINGS.QUEUE_MAX

    @retry
    def get_job(self, name):
        self.load()
        instance = self._instance.get_job(name)
        instance.poll()
        return Job.factory(instance)

    @retry
    @asyncio.coroutine
    def aget_job(self, name):
        self.load()
        instance = self._instance.get_job(name)
        client = RESTClient(instance.baseurl)
        instance._data = yield from client.aget()
        instance._config = yield from client('config.xml').afetch()
        return Job.factory(instance)

    DESCRIPTION_TMPL = """\
%(description)s

<!--
%(embedded_data)s
-->
"""

    def preprocess_spec(self, spec):
        embedded_data = dict(updated_at=datetime.utcnow())
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
        api_instance.poll()
        return Job.factory(api_instance)

    @retry
    def update_job(self, job_spec):
        api_instance = self._instance.get_job(job_spec.name)
        job_spec = self.preprocess_spec(job_spec)
        config = job_spec.as_xml()
        if SETTINGS.DRY_RUN:
            logger.warn("Would update Jenkins job %s.", job_spec)
            api_instance.poll()
            return Job.factory(api_instance)

        api_instance.update_config(config)
        logger.warn("Updated Jenkins job %s.", job_spec.name)
        api_instance.poll()
        return Job.factory(api_instance)


JENKINS = LazyJenkins()


class Build(object):
    def __init__(self, job, payload):
        self.job = job
        self.payload = payload
        self.actions = self.process_actions(payload)
        self.params = self.process_params(self.actions)

    @staticmethod
    def process_actions(payload):
        known_actions = {'lastBuiltRevision', 'parameters'}
        actions = {}
        for action in payload.get('actions', []):
            for known in known_actions:
                if known in action:
                    actions[known] = action[known]
        return actions

    @staticmethod
    def process_params(actions):
        return {
            p['name']: p['value']
            for p in actions.get('parameters', [])
            if 'value' in p
        }

    jenkins_tree = (
        "actions[" + (
            "parameters[name,value],"
            "lastBuiltRevision[branch[name,SHA1]]"
        ) + "],"
        "building,displayName,duration,fullDisplayName,"
        "number,result,timestamp,url"
    )

    @classmethod
    @asyncio.coroutine
    def from_url(cls, url):
        if not url.startswith(SETTINGS.JENKINS_URL):
            raise NotOnJenkins("%s is not on this Jenkins." % url)

        payload = yield from RESTClient(url).aget(tree=cls.jenkins_tree)
        return Build(None, payload)

    def __getattr__(self, name):
        return self.payload[name]

    def __repr__(self):
        return '<%s %s>' % (
            self.__class__.__name__, self.payload['fullDisplayName']
        )

    def __str__(self):
        return str(self.payload['fullDisplayName'])

    _status_map = {
        # Requeue an aborted job
        'ABORTED': ('error', 'Aborted!'),
        'FAILURE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'UNSTABLE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'SUCCESS': ('success', 'Build %(name)s succeeded in %(duration)s!'),
        None: ('pending', 'Build %(name)s in progress...'),
    }

    @property
    def commit_status(self):
        state, description = self._status_map[self.payload.get('result')]
        description = description % dict(
            name=self.payload['displayName'],
            duration=format_duration(self.payload['duration']),
        )
        return dict(
            description=description, state=state,
            target_url=self.payload['url'],
        )

    @property
    def is_outdated(self):
        now = datetime.now()
        maxage = timedelta(hours=2)
        seconds = self.payload['timestamp'] / 1000.
        build_date = datetime.fromtimestamp(seconds)
        if build_date > now:
            logger.warning(
                "Build %s in the future. Is timezone correct?", self
            )
            return False
        build_age = now - build_date
        return build_age > maxage

    @property
    def is_running(self):
        return self.payload['building']

    _ref_re = re.compile(r'.*origin/(?P<ref>.*)')

    @property
    def ref(self):
        try:
            fullref = self.actions['lastBuiltRevision']['branch'][0]['name']
        except (IndexError, KeyError, TypeError):
            return self.params[self.job.revision_param][len('refs/heads/'):]
        else:
            match = self._ref_re.match(fullref)
            if not match:
                raise Exception("Unknown branch %s" % fullref)
            return match.group('ref')

    @property
    def sha(self):
        try:
            return self.actions['lastBuiltRevision']['branch'][0]['SHA1']
        except (IndexError, KeyError, TypeError) as e:
            raise Exception("No SHA1 yet.") from e

    @asyncio.coroutine
    def stop(self):
        payload = yield from RESTClient(self.payload['url']).stop.apost()
        return payload


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

    @asyncio.coroutine
    def fetch_builds(self):
        tree = "builds[" + Build.jenkins_tree + "]"
        payload = yield from RESTClient(self.baseurl).aget(tree=tree)
        return payload['builds']

    def process_builds(self, payload):
        payload = reversed(sorted(payload, key=lambda b: b['number']))
        return (Build(self, entry) for entry in payload)


class FreestyleJob(Job):
    def list_contexts(self, spec):
        yield self._instance.name

    def build(self, pr, spec, contexts):
        log = str(self)
        params = spec.config.get('parameters', {}).copy()
        if self.revision_param:
            params[self.revision_param] = pr.fullref
            log += ' for %s' % pr.ref

        if 'node' in spec.config:
            if self.node_param:
                params[self.node_param] = spec.config['node']
            else:
                logger.warn(
                    "Can't assign build to node %s.", spec.config['node'],
                )

        params['YML_NOTIFY_URL'] = fullurl(head=pr.url)

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
            axis.append([
                '%s=%s' % (name, v)
                for v in sorted(map(str, values))
            ])

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
        build_params = {'YML_NOTIFY_URL': fullurl(head=pr.url)}

        for name, value in spec.config.get('parameters', {}).items():
            build_params[name] = value

        if self.revision_param:
            build_params[self.revision_param] = pr.fullref

        if self.combination_param:
            conf_index = len(str(self))+1
            conditions = []
            not_built = [c[conf_index:] for c in contexts]
            for name in not_built:
                condition = (
                    name
                    .replace('=', ' == "')
                    .replace(',', '" && ')
                    + '"'
                )
                conditions.append('(%s)' % condition)

            build_params[self.combination_param] = ' || '.join(conditions)

        if SETTINGS.DRY_RUN:
            for context in contexts:
                logger.info("Would trigger %s for %s", context, pr.ref)
            return

        self._instance.invoke(build_params=build_params, delay=0, cause='EPO')

        for context in contexts:
            log = '%s/%s' % (self, context)
            if self.revision_param:
                log += ' for %s' % pr.ref
            logger.info("Triggered new build %s", log)
