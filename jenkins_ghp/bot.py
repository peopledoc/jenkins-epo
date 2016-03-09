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
import datetime
import inspect
import logging
import pkg_resources
import re
import socket
import yaml

from .jenkins import JENKINS
from .project import Branch
from .utils import parse_datetime
from .settings import SETTINGS


logger = logging.getLogger(__name__)


class Bot(object):
    DEFAULTS = {
        'errors': [],
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
        self.head = head
        self.settings = copy.deepcopy(self.DEFAULTS)
        for ext in self.extensions.values():
            self.settings.update(copy.deepcopy(ext.DEFAULTS))
        return self

    def run(self, head):
        self.workon(head)

        for ext in self.extensions.values():
            ext.begin()

        self.process_instructions()
        logger.debug("Bot settings: %r", self.settings)

        for ext in self.extensions.values():
            ext.end()

    def process_instructions(self):
        process = True
        for date, author, data in self.head.list_instructions():
            try:
                data = yaml.load(data)
            except yaml.error.YAMLError as e:
                self.settings['errors'].append((author, data, e))
                continue

            data = data['jenkins']
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
        self.bot.settings.update(copy.deepcopy(self.DEFAULTS))

    def process_instruction(self, instruction):
        pass

    def end(self):
        pass


class BuilderExtension(Extension):
    """
    # Skipping jobs
    jenkins: skip
    jenkins: {skip: '(?!except-this)'}
    jenkins:
    skip: ['this.*', 'that']

    # Requeue past failed jobs
    jenkins: rebuild
    """

    DEFAULTS = {
        'skip': [],
        'skip-errors': [],
        'rebuild-failed': None,
    }
    SKIP_ALL = ('.*',)
    ERROR_COMMENT = """
Sorry %(mention)s, I don't understand your pattern `%(pattern)r`: `%(error)s`.

<!--
jenkins: reset-skip-errors
-->
"""

    def process_instruction(self, instruction):
        if instruction == 'skip':
            patterns = instruction.args
            if isinstance(patterns, str):
                patterns = [patterns]
            patterns = patterns or self.SKIP_ALL
            self.bot.settings['skip'] = skip = []
            self.bot.settings['skip-errors'] = errors = []
            for pattern in patterns:
                try:
                    skip.append(re.compile(pattern))
                except re.error as e:
                    logger.warn("Bad pattern for skip: %s", e)
                    errors.append((instruction, pattern, e))
        if instruction == 'reset-skip-errors':
            self.bot.settings['skip-errors'] = []
        elif instruction == 'rebuild':
            self.bot.settings['rebuild-failed'] = instruction.date

    def end(self):
        for instruction, pattern, error in self.bot.settings['skip-errors']:
            self.bot.head.comment(self.ERROR_COMMENT % dict(
                mention='@' + instruction.author,
                pattern=pattern,
                error=str(error),
            ))

        for job in self.bot.head.project.jobs:
            not_built = self.bot.head.filter_not_built_contexts(
                job.list_contexts(),
                rebuild_failed=self.bot.settings['rebuild-failed']
            )

            for context in not_built:
                self.bot.head.update_statuses(
                    target_url=job.baseurl,
                    **self.status_for_new_context(context)
                )

            queued_contexts = [c for c in not_built if not self.skip(c)]
            if queued_contexts and self.bot.queue_empty:
                try:
                    job.build(self.bot.head, queued_contexts)
                except Exception as e:
                    logger.warn("Failed to queue job %s: %s", job, e)
                    for context in queued_contexts:
                        self.bot.head.update_statuses(
                            context=context,
                            state='failure',
                            description='Failed to queue job',
                            target_url=job.baseurl,
                        )

    def skip(self, context):
        for pattern in self.bot.settings['skip']:
            if pattern.match(context):
                return True

    def status_for_new_context(self, context):
        new_status = {'context': context}
        if self.skip(context):
            new_status.update({
                'description': 'Skipped',
                'state': 'success',
            })
        else:
            current_status = self.bot.head.get_status_for(context)
            already_queued = 'Queued' == current_status.get('description')
            queued = self.bot.queue_empty or already_queued
            new_status.update({
                'description': 'Queued' if queued else 'Backed',
                'state': 'pending',
            })
        return new_status


def format_duration(duration):
    duration = datetime.timedelta(seconds=duration / 1000.)
    h, m, s = str(duration).split(':')
    h, m, s = int(h), int(m), float(s)
    duration = '%.1f sec' % s
    if h or m:
        duration = '%d min %s' % (m, duration)
    if h:
        duration = '%d h %s' % (h, duration)
    return duration.replace('.0', '')


class FixStatusExtension(Extension):
    SETTINGS = {
        'GHP_STATUS_LOOP': 300,
    }

    status_map = {
        # Requeue an aborted job
        'ABORTED': ('pending', 'Backed'),
        'FAILURE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'SUCCESS': ('success', 'Build %(name)s succeeded in %(duration)s'),
    }

    def compute_actual_status(self, build, current_status):
        target_url = current_status['target_url']
        # If no build found, this may be an old CI build, or any other
        # unconfirmed build. Retrigger.
        jenkins_status = build.get_status() if build else 'ABORTED'
        if jenkins_status:
            state, description = self.status_map[jenkins_status]
            if description == 'Backed':
                target_url = None
            else:
                duration = format_duration(build._data['duration'])
                try:
                    description = description % dict(
                        name=build._data['displayName'],
                        duration=duration,
                    )
                except TypeError:
                    pass
        else:
            # Touch the commit status to avoid polling it for the next 5
            # minutes.
            state = 'pending'
            description = current_status['description']
            ellipsis = '...' if description.endswith('....') else '....'
            description = description.rstrip('.') + ellipsis

        return dict(
            description=description, state=state, target_url=target_url,
        )

    def end(self):
        fivemin_ago = (
            datetime.datetime.utcnow() -
            datetime.timedelta(seconds=SETTINGS.GHP_STATUS_LOOP)
        )

        failed_contexts = []
        for context, status in sorted(self.bot.head.get_statuses().items()):
            if status['state'] == 'success':
                continue

            updated_at = parse_datetime(status['updated_at'])
            # Don't poll Jenkins more than each 5 min.
            if status['state'] == 'pending' and updated_at > fivemin_ago:
                continue

            # There is no build URL.
            if status['description'] in {'Backed', 'New', 'Queued'}:
                continue

            # We mark actual failed with a bang to avoid rechecking it is
            # aborted.
            if status['description'].endswith('!'):
                continue

            logger.debug("Query %s status on Jenkins", context)
            try:
                build = JENKINS.get_build_from_url(status['target_url'])
            except Exception as e:
                logger.debug(
                    "Failed to get actual build status for contexts: %s: %s",
                    e.__class__.__name__, e,
                )
                build = None
                failed_contexts.append(context)

            self.bot.head.update_statuses(
                context=context, **self.compute_actual_status(build, status)
            )

        if failed_contexts:
            logger.warn(
                "Failed to get actual build status for contexts: %s",
                failed_contexts
            )


class HelpExtension(Extension):
    DEFAULTS = {
        'help-mentions': set(),
    }
    DISTRIBUTION = pkg_resources.get_distribution('jenkins_ghp')
    HELP = """\
<!--
jenkins: ignore
-->

%(mentions)s: this is what I understand:

```yaml
%(help)s
```

You can mix instructions. Multiline instructions **must** be in code block.

--
*%(me)s for your service*

<!--
jenkins: [process, help-reset]

Running %(software)s==%(version)s on %(host)s
Extensions: %(extensions)s
-->
"""

    def process_instruction(self, instruction):
        if instruction.name in ('help', 'man'):
            self.bot.settings['help-mentions'].add(instruction.author)
        elif instruction == 'help-reset':
            self.bot.settings['help-mentions'] = set()

    def generate_comment(self):
        docs = []
        for ext in self.bot.extensions.values():
            doc = ext.__class__.__doc__
            if not doc:
                continue
            docs.append(inspect.cleandoc(doc))
        help_ = '\n\n'.join(docs)
        return self.HELP % dict(
            extensions=','.join(sorted(self.bot.extensions.keys())),
            help=help_,
            host=socket.getfqdn(),
            me=SETTINGS.GHP_NAME,
            mentions=', '.join(sorted([
                '@' + m for m in self.bot.settings['help-mentions']
            ])),
            software=self.DISTRIBUTION.project_name,
            version=self.DISTRIBUTION.version,
        )

    def answer_help(self):
        self.bot.head.comment(self.generate_comment())

    def end(self):
        if self.bot.settings['help-mentions']:
            self.answer_help()


class ErrorExtension(Extension):
    ERROR_COMMENT = """
Sorry %(mention)s, I don't understand what you mean by `%(instruction)s`: `%(error)s`.

See `jenkins: help` for documentation.

<!--
jenkins: reset-errors
-->
"""  # noqa

    def process_instruction(self, instruction):
        if instruction == 'reset-errors':
            self.bot.settings['errors'] = []

    def end(self):
        for author, instruction, error in self.bot.settings['errors']:
            self.bot.head.comment(self.ERROR_COMMENT % dict(
                mention='@' + author,
                instruction=repr(instruction),
                error=str(error),
            ))


class ReportExtension(Extension):
    ISSUE_TEMPLATE = """
Commit %(abbrev)s is broken on %(branch)s:

%(builds)s
"""
    COMMENT_TEMPLATE = """
Build failure reported at #%(issue)s.

<!--
jenkins: report-done
-->
"""

    DEFAULTS = {
        # Issue URL where the failed builds are reported.
        'report-done': False,
    }

    def process_instruction(self, instruction):
        if instruction == 'report-done':
            self.bot.settings['report-done'] = True

    def end(self):
        if self.bot.settings['report-done']:
            return

        if not isinstance(self.bot.head, Branch):
            return

        statuses = self.bot.head.get_statuses()
        errored = [
            s for s in statuses.values()
            if s['state'] in {'failure', 'error'}
        ]
        if not errored:
            return

        branch_name = self.bot.head.ref[len('refs/heads/'):]
        builds = '- ' + '\n- '.join([s['target_url'] for s in errored])
        issue = self.bot.head.project.report_issue(
            title="%s is broken" % (branch_name,),
            body=self.ISSUE_TEMPLATE % dict(
                abbrev=self.bot.head.sha[:7],
                branch=branch_name,
                builds=builds,
                sha=self.bot.head.sha,
                ref=self.bot.head.ref,
            )
        )

        self.bot.head.comment(body=self.COMMENT_TEMPLATE % dict(
            issue=issue['number']
        ))
