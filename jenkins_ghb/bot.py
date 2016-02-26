import logging
import re


logger = logging.getLogger(__name__)


class Bot(object):
    DEFAULTS = {
        'skip': (),
        'rebuild-failed': None,
    }
    SKIP_ALL = ('.*',)

    def __init__(self, queue_empty=True):
        self.queue_empty = queue_empty
        self.settings = {}

    def load_instructions(self, pr):
        self.settings = self.DEFAULTS.copy()
        for date, instruction in pr.list_instructions():
            if isinstance(instruction, str):
                instruction = instruction.lower()
                if instruction == 'skip':
                    self.settings['skip'] = self.SKIP_ALL
                elif instruction == 'rebuild':
                    self.settings['rebuild-failed'] = date
                else:
                    logger.warn("I don't understand %r", instruction)
            elif isinstance(instruction, dict):
                if 'skip' in instruction:
                    skip = instruction['skip']
                    if isinstance(skip, str):
                        skip = [skip]
                    elif skip is None:
                        skip = self.SKIP_ALL

                    self.settings['skip'] = skip
            else:
                logger.warn("I don't understand %r", instruction)
        logger.debug("Bot settings: %r", self.settings)

    def run(self, pr):
        logger.info("Working on %s", pr)
        self.load_instructions(pr)
        self.build(pr)

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
            not_built = job.list_not_built_contextes(
                pr, rebuild_failed=self.settings['rebuild-failed']
            )
            if not_built and self.queue_empty:
                job.build(pr, [c for c in not_built if not self.skip(c)])

            for context in not_built:
                pr.update_statuses(**self.status_for_new_context(context))

    def skip(self, context):
        for pattern in self.settings['skip']:
            try:
                if re.match(pattern, context):
                    return True
            except re.error as e:
                logger.warn("Bad pattern for skip: %s", e)
