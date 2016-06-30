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

import collections
import copy
import logging
import pkg_resources
import re
import reprlib
import yaml

from .github import GITHUB, ApiNotFoundError
from .jenkins import JENKINS
from .repository import JobSpec
from .settings import SETTINGS
from .utils import Bunch, parse_datetime


logger = logging.getLogger(__name__)


class Bot(object):
    DEFAULTS = {
        'errors': [],
        'jobs': [],
    }

    instruction_re = re.compile(
        '('
        # Case beginning:  jenkins: ... or `jenkins: ...`
        '\A`*jenkins:[^\n]*`*' '|'
        # Case one middle line:  jenkins: ...
        '(?!`)\njenkins:[^\n]*' '|'
        # Case middle line teletype:  `jenkins: ...`
        '\n`+jenkins:[^\n]*`+' '|'
        # Case block code: ```\njenkins:\n  ...```
        '```(?:yaml)?\njenkins:[\s\S]*?\n```'
        ')'
    )

    def __init__(self, queue_empty=True):
        self.queue_empty = queue_empty
        self.extensions = {}
        for ep in pkg_resources.iter_entry_points(__name__ + '.extensions'):
            cls = ep.load()
            self.extensions[ep.name] = ext = cls(ep.name, self)
            SETTINGS.load(ext.SETTINGS)
            logger.debug("Loaded extension %s", ep.name)

    def workon(self, head):
        logger.info("Working on %s.", head)
        self.current = Bunch(copy.deepcopy(self.DEFAULTS))
        self.current.head = head
        for ext in self.extensions.values():
            self.current.update(copy.deepcopy(ext.DEFAULTS))
            ext.current = self.current
        return self

    def run(self, head):
        self.workon(head)

        try:
            jenkins_yml = GITHUB.fetch_file_contents(
                head.repository, 'jenkins.yml', ref=head.ref,
            )
            logger.debug("Loading jenkins.yml.")
        except ApiNotFoundError:
            jenkins_yml = None

        for job in head.repository.list_jobs(jenkins_yml):
            if isinstance(job, JobSpec):
                job = JENKINS.create_job(job)

            if job and job.managed:
                self.current.jobs.append(job)

        payload = self.current.head.fetch_statuses()
        self.current.head.process_statuses(payload)
        self.current.statuses = self.current.head.statuses
        for ext in self.extensions.values():
            ext.begin()

        self.process_instructions(self.current.head.list_comments())
        repr_ = reprlib.Repr()
        repr_.maxdict = repr_.maxlist = repr_.maxother = 64
        vars_repr = repr_.repr1(dict(self.current), 2)
        logger.debug("Bot vars: %s", vars_repr)

        for ext in self.extensions.values():
            ext.end()

    def parse_instructions(self, comments):
        process = True
        for comment in comments:
            if comment['body'] is None:
                continue

            body = comment['body'].replace('\r', '')
            for stanza in self.instruction_re.findall(body):
                stanza = stanza.strip().strip('`')
                if stanza.startswith('yaml\n'):
                    stanza = stanza[4:].strip()

                date = parse_datetime(comment['updated_at'])
                author = comment['user']['login']

                try:
                    payload = yaml.load(stanza)
                except yaml.error.YAMLError as e:
                    self.current.errors.append((author, stanza, e))
                    continue

                data = payload.pop('jenkins')
                # If jenkins is empty, reset to dict
                data = data or {}
                # If spurious keys are passed, this may be an unindented yaml,
                # just include it.
                if payload:
                    data = dict(payload, **data)

                if not data:
                    continue
                if isinstance(data, str):
                    data = {data: None}
                if isinstance(data, list):
                    data = collections.OrderedDict(zip(data, [None]*len(data)))

                for name, args in data.items():
                    name = name.lower()
                    instruction = Instruction(name, args, author, date)
                    if not process:
                        process = 'process' == instruction
                        continue
                    elif instruction == 'ignore':
                        process = False
                    else:
                        yield instruction

    def process_instructions(self, comments):
        for instruction in self.parse_instructions(comments):
            for ext in self.extensions.values():
                ext.process_instruction(instruction)


class Instruction(object):
    def __init__(self, name, args, author, date):
        self.name = name
        self.args = args
        self.author = author
        self.date = date

    def __str__(self):
        return self.name

    def __repr__(self):
        return '%s(%s, %s)' % (
            self.__class__.__name__,
            self.author, self.name
        )

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        else:
            return super(Instruction, self).__eq__(other)


class Extension(object):
    DEFAULTS = {}
    SETTINGS = {}

    def __init__(self, name, bot):
        self.name = name
        self.bot = bot

    def begin(self):
        self.bot.current.update(copy.deepcopy(self.DEFAULTS))

    def process_instruction(self, instruction):
        pass

    def end(self):
        pass
