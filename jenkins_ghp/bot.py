import collections
import copy
import inspect
import logging
import pkg_resources
import re
import socket

from .settings import SETTINGS


logger = logging.getLogger(__name__)


class Bot(object):
    DEFAULTS = {
        'help-mentions': set(),
        'skip': (),
        'rebuild-failed': None,
    }

    def __init__(self, queue_empty=True):
        self.queue_empty = queue_empty
        self.extensions = {}
        for ep in pkg_resources.iter_entry_points(__name__ + '.extensions'):
            cls = ep.load()
            self.extensions[ep.name] = ext = cls(ep.name, self)
            SETTINGS.load(ext.SETTINGS)
            logger.info("Loaded extension %s", ep.name)

    def workon(self, pr):
        logger.info("Working on %s", pr)
        self.pr = pr
        self.settings = copy.deepcopy(self.DEFAULTS)
        return self

    def run(self, pr):
        self.workon(pr)

        for ext in self.extensions.values():
            ext.begin()

        self.process_instructions()
        logger.debug("Bot settings: %r", self.settings)

        for ext in self.extensions.values():
            ext.end()

    def process_instructions(self):
        process = True
        for date, author, data in self.pr.list_instructions():
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
        'rebuild-failed': None,
    }
    SKIP_ALL = ('.*',)

    def process_instruction(self, instruction):
        if instruction == 'skip':
            patterns = instruction.args
            if isinstance(patterns, str):
                patterns = [patterns]
            self.bot.settings['skip'] = patterns or self.SKIP_ALL
        elif instruction == 'rebuild':
            self.bot.settings['rebuild-failed'] = instruction.date

    def end(self):
        for job in self.bot.pr.project.jobs:
            not_built = self.bot.pr.filter_not_built_contexts(
                job.list_contexts(),
                rebuild_failed=self.bot.settings['rebuild-failed']
            )
            if not_built and self.bot.queue_empty:
                job.build(
                    self.bot.pr, [c for c in not_built if not self.skip(c)]
                )

            for context in not_built:
                self.bot.pr.update_statuses(
                    **self.status_for_new_context(context)
                )

    def skip(self, context):
        for pattern in self.bot.settings['skip']:
            try:
                if re.match(pattern, context):
                    return True
            except re.error as e:
                logger.warn("Bad pattern for skip: %s", e)

    def status_for_new_context(self, context):
        new_status = {'context': context}
        if self.skip(context):
            new_status.update({
                'description': 'Skipped',
                'state': 'success',
            })
        else:
            new_status.update({
                'description': 'Queued' if self.bot.queue_empty else 'Backed',
                'state': 'pending',
            })
        return new_status


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
            me='Jenkins GitHub Builder',
            mentions=', '.join(sorted([
                '@' + m for m in self.bot.settings['help-mentions']
            ])),
            software=self.DISTRIBUTION.project_name,
            version=self.DISTRIBUTION.version,
        )

    def answer_help(self):
        self.bot.pr.comment(self.generate_comment())

    def end(self):
        if self.bot.settings['help-mentions']:
            self.answer_help()
