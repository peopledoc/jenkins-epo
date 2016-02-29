import copy
import logging
import pkg_resources
import re
import socket


logger = logging.getLogger(__name__)
DISTRIBUTION = pkg_resources.get_distribution('jenkins_ghp')
HELP = """\
<!--
jenkins: ignore
-->

%(mentions)s, this is what I understand:

```yaml
# Skipping jobs
jenkins: skip
jenkins: {skip: '(?!except-this)'}
jenkins:
  skip: ['this.*', 'that']

# Requeue past failed jobs
jenkins: rebuild

# Ask for manual
jenkins: help|man
```

You can mix instructions. Multiline instructions **must** be in code block.

--
*%(me)s for your service*

<!--
jenkins: [process, help-reset]

Running %(software)s==%(version)s on %(host)s
-->
"""


class Bot(object):
    DEFAULTS = {
        'actions': set(),
        'help-mentions': set(),
        'skip': (),
        'rebuild-failed': None,
    }
    SKIP_ALL = ('.*',)

    def __init__(self, queue_empty=True):
        self.queue_empty = queue_empty
        self.settings = {}

    def load_instructions(self, pr):
        self.settings = copy.deepcopy(self.DEFAULTS)
        self.settings['actions'].add(self.build)
        process = True
        for date, author, instructions in pr.list_instructions():
            if isinstance(instructions, str):
                instructions = [instructions]
            for instruction in instructions:
                instruction = instruction.lower()
                if not process:
                    process = 'process' == instruction
                    continue
                if instruction == 'skip':
                    patterns = None
                    if isinstance(instructions, dict):
                        patterns = instructions['skip']
                        if isinstance(patterns, str):
                            patterns = [patterns]
                    self.settings['skip'] = patterns or self.SKIP_ALL
                elif instruction == 'rebuild':
                    self.settings['rebuild-failed'] = date
                elif instruction in ('help', 'man'):
                    self.settings['actions'].add(self.help_)
                    self.settings['help-mentions'].add(author)
                elif instruction == 'help-reset':
                    try:
                        self.settings['actions'].remove(self.help_)
                    except KeyError:
                        pass
                    self.settings['help-mentions'] = set()
                elif instruction == 'ignore':
                    process = False
                else:
                    logger.warn("I don't understand %r", instruction)

        logger.debug("Bot settings: %r", self.settings)

    def run(self, pr):
        logger.info("Working on %s", pr)
        self.load_instructions(pr)
        for action in self.settings['actions']:
            action(pr)

    def status_for_new_context(self, context):
        new_status = {'context': context}
        if self.skip(context):
            new_status.update({
                'description': 'Skipped',
                'state': 'success',
            })
        else:
            new_status.update({
                'description': 'Queued' if self.queue_empty else 'Backed',
                'state': 'pending',
            })
        return new_status

    def build(self, pr):
        for job in pr.project.jobs:
            not_built = pr.filter_not_built_contexts(
                job.list_contexts(),
                rebuild_failed=self.settings['rebuild-failed']
            )
            if not_built and self.queue_empty:
                job.build(pr, [c for c in not_built if not self.skip(c)])

            for context in not_built:
                pr.update_statuses(**self.status_for_new_context(context))

    def help_(self, pr):
        pr.comment(HELP % dict(
            host=socket.getfqdn(),
            me='Jenkins GitHub Builder',
            mentions=','.join([
                '@' + m for m in self.settings['help-mentions']
            ]),
            software=DISTRIBUTION.project_name,
            version=DISTRIBUTION.version,
        ))

    def skip(self, context):
        for pattern in self.settings['skip']:
            try:
                if re.match(pattern, context):
                    return True
            except re.error as e:
                logger.warn("Bad pattern for skip: %s", e)
