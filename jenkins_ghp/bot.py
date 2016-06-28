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
import yaml

from .jenkins import JENKINS
from .repository import JobSpec
from .settings import SETTINGS
from .utils import Bunch


logger = logging.getLogger(__name__)


class Bot(object):
    DEFAULTS = {
        'errors': [],
        'jobs': [],
    }

    def __init__(self, queue_empty=True):
        self.queue_empty = queue_empty
        self.extensions = {}
        for ep in pkg_resources.iter_entry_points(__name__ + '.extensions'):
            cls = ep.load()
            self.extensions[ep.name] = ext = cls(ep.name, self)
            SETTINGS.load(ext.SETTINGS)
            logger.debug("Loaded extension %s", ep.name)

    def workon(self, head):
        logger.info("Working on %s", head)
        self.current = Bunch(copy.deepcopy(self.DEFAULTS))
        self.current.head = head
        for ext in self.extensions.values():
            self.current.update(copy.deepcopy(ext.DEFAULTS))
            ext.current = self.current
        return self

    def run(self, head):
        self.workon(head)

        for job in head.list_jobs():
            if isinstance(job, JobSpec):
                job = JENKINS.create_job(job)

            if job and job.managed:
                self.current.jobs.append(job)

        for ext in self.extensions.values():
            ext.begin()

        self.process_instructions()
        logger.debug("Bot vars: %r", self.current)

        for ext in self.extensions.values():
            ext.end()

    def process_instructions(self):
        process = True
        for date, author, data in self.current.head.list_instructions():
            try:
                payload = yaml.load(data)
            except yaml.error.YAMLError as e:
                self.current.errors.append((author, data, e))
                continue

            data = payload.pop('jenkins')
            # If jenkins is empty, reset to dict
            data = data or {}
            # If spurious keys are passed, this may be an unindented yaml, just
            # include it.
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
