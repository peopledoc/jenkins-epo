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
import random
import re
import socket
import yaml

from .jenkins import JENKINS
from .project import ApiError, Branch, JobSpec, PullRequest
from .utils import match, parse_datetime
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
        self.current = copy.deepcopy(self.DEFAULTS)
        for ext in self.extensions.values():
            self.current.update(copy.deepcopy(ext.DEFAULTS))

        self.jobs = []
        for job in head.list_jobs():
            if not match(job.name, JENKINS.jobs_filter):
                logger.debug("Skipping %s", job.name)
                continue

            if isinstance(job, JobSpec):
                job = JENKINS.create_job(job)

            if job and job.push_trigger:
                self.jobs.append(job)

        return self

    def run(self, head):
        self.workon(head)

        for ext in self.extensions.values():
            ext.begin()

        self.process_instructions()
        logger.debug("Bot vars: %r", self.current)

        for ext in self.extensions.values():
            ext.end()

    def process_instructions(self):
        process = True
        for date, author, data in self.head.list_instructions():
            try:
                payload = yaml.load(data)
            except yaml.error.YAMLError as e:
                self.current['errors'].append((author, data, e))
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


class BuilderExtension(Extension):
    """
    # Selecting jobs
    jenkins:
      jobs: only*  # Build only prefixed
      jobs: ['*', -glob*]  # skip prefixed with glob
      jobs: ['*', +add*, -skip*]

    # Skipping jobs
    jenkins: skip
    jenkins: {skip: '(?!except-this)'}
    jenkins:
      skip: ['this.*', 'that']

    # Requeue past failed jobs
    jenkins: rebuild

    # Acknowledge for auto-merge
    jenkins: opm
    """

    DEFAULTS = {
        'jobs-match': [],
        'lgtm': [],
        'lgtm-processed': None,
        'skip': [],
        'skip-errors': [],
        'rebuild-failed': None,
    }
    SETTINGS = {
        'GHP_LGTM_AUTHOR': False,
        'GHP_LGTM_QUORUM': 1,
    }
    SKIP_ALL = ('.*',)
    BUILD_ALL = ['*']

    ERROR_COMMENT = """
Sorry %(mention)s, I don't understand your pattern `%(pattern)r`: `%(error)s`.

<!--
jenkins: reset-skip-errors
-->
"""
    LGTM_COMMENT = """
%(mention)s, %(message)s %(emoji)s

<!--
jenkins: lgtm-processed
-->
"""

    def begin(self):
        super(BuilderExtension, self).begin()

        if isinstance(self.bot.head, PullRequest):
            # Initialize LGTM processing
            self.bot.current['lgtm-processed'] = parse_datetime(
                self.bot.head.data['created_at']
            )

    def process_instruction(self, instruction):
        if instruction == 'skip':
            patterns = instruction.args
            if isinstance(patterns, str):
                patterns = [patterns]
            patterns = patterns or self.SKIP_ALL
            self.bot.current['skip'] = skip = []
            self.bot.current['skip-errors'] = errors = []
            for pattern in patterns:
                try:
                    skip.append(re.compile(pattern))
                except re.error as e:
                    logger.warn("Bad pattern for skip: %s", e)
                    errors.append((instruction, pattern, e))
        elif instruction == 'jobs':
            patterns = instruction.args
            if isinstance(patterns, str):
                patterns = [patterns]

            self.bot.current['jobs-match'] = patterns
        elif instruction in {'lgtm', 'merge', 'opm'}:
            if hasattr(self.bot.head, 'merge'):
                if not self.bot.current['lgtm']:
                    logger.debug("LGTM incoming.")
                self.bot.current['lgtm'].append(instruction)
        elif instruction == 'lgtm-processed':
            self.bot.current['lgtm-processed'] = instruction.date
        elif instruction == 'reset-skip-errors':
            self.bot.current['skip-errors'] = []
        elif instruction == 'rebuild':
            self.bot.current['rebuild-failed'] = instruction.date

    def end(self):
        for instruction, pattern, error in self.bot.current['skip-errors']:
            self.bot.head.comment(self.ERROR_COMMENT % dict(
                mention='@' + instruction.author,
                pattern=pattern,
                error=str(error),
            ))

        for job in self.bot.jobs:
            not_built = self.bot.head.filter_not_built_contexts(
                job.list_contexts(),
                rebuild_failed=self.bot.current['rebuild-failed']
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
                            state='error',
                            description='Failed to queue job',
                            target_url=job.baseurl,
                        )

        self.maybe_merge()

    def check_lgtm(self):
        logger.debug("Validating LGTMs.")
        lgtms = self.bot.current['lgtm'][:]
        if not lgtms:
            return

        processed_date = self.bot.current['lgtm-processed']

        lgtmers = {i.author for i in lgtms}
        new_refused = set()
        for author in list(lgtmers):
            if author in self.bot.head.project.SETTINGS.GHP_REVIEWERS:
                logger.info("Accept @%s as reviewer.", author)
            else:
                lgtmers.remove(author)
                logger.info("Refuse LGTM from @%s.", author)
                unanswerd_lgtm = [
                    l for l in lgtms
                    if l.author == author and l.date > processed_date
                ]
                if unanswerd_lgtm:
                    new_refused.add(author)

        if new_refused:
            self.bot.head.comment(self.LGTM_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention=', '.join(sorted(['@' + a for a in new_refused])),
                message="you're not allowed to acknowledge PR",
            ))

        lgtms = [i for i in lgtms if i.author in lgtmers]
        if not lgtms:
            return logger.debug("No legal LGTMs. Skipping.")

        commit = self.bot.head.get_commit()
        commit_date = parse_datetime(commit['committer']['date'])
        outdated_lgtm = [l for l in lgtms if l.date < commit_date]
        lgtms = list(set(lgtms) - set(outdated_lgtm))
        if outdated_lgtm and not lgtms:
            logger.debug("PR updated since LGTM. Skipping.")
            unanswerd_lgtm = [
                l for l in outdated_lgtm if l.date > processed_date
            ]
            if unanswerd_lgtm:
                mentions = sorted(set([
                    '@' + l.author for l in unanswerd_lgtm
                ]))
                self.bot.head.comment(self.LGTM_COMMENT % dict(
                    emoji=random.choice((':up:', ':point_up:')),
                    mention=', '.join(mentions),
                    message=(
                        "PR has been updated since your acknowledgement. "
                        "I don't merge updated PR."
                    ),
                ))
            return

        lgtmers = {i.author for i in lgtms}
        if len(lgtms) > len(lgtmers):
            logger.debug("Deduplicate LGTMs")
            lgtms = [
                [l for l in lgtms if l.author == a][0] for a in lgtmers
            ]

        if len(lgtms) < self.bot.head.project.SETTINGS.GHP_LGTM_QUORUM:
            return logger.debug("Missing LGTMs quorum. Skipping.")

        if self.bot.head.project.SETTINGS.GHP_LGTM_AUTHOR:
            self_lgtm = self.bot.head.author in {i.author for i in lgtms}
            if not self_lgtm:
                return logger.debug("Author's LGTM missing. Skipping.")

        logger.debug("Accepted LGTMs from %s", [l.author for l in lgtms])

        return lgtms

    def check_mergeable(self):
        # This function loop the checklist for an automergeable PR. The
        # checklist summary is:
        #
        # 1. LGTM quorum is ok ;
        # 2. All managed status are green ;
        # 3. PR is not behind base branch.
        #
        # If any item of the checklist fails, PR must be merge manually.

        lgtms = self.check_lgtm()
        if not lgtms:
            return

        statuses = self.bot.head.get_statuses()
        unsuccess = {
            k: v for k, v in statuses.items()
            if v['state'] != 'success'
        }
        if unsuccess:
            return logger.debug("PR not green. Postpone merge.")

        if self.bot.head.is_behind():
            logger.debug("Base updated since LGTM. Skipping merge.")
            unprocessed_lgtms = [
                l for l in lgtms
                if l.date > self.bot.current['lgtm-processed']
            ]
            if unprocessed_lgtms:
                self.bot.head.comment(self.LGTM_COMMENT % dict(
                    emoji=random.choice((':confused:', ':disappointed:')),
                    mention='@' + self.bot.head.author,
                    message=(
                        "%(base)s has been updated and this PR is now behind. "
                        "I don't merge behind PR." % dict(
                            base=self.bot.head.data['base']['label'],
                        )
                    ),
                ))
            return

        return lgtms

    def maybe_merge(self):
        lgtms = self.check_mergeable()
        if not lgtms:
            return

        try:
            self.bot.head.merge()
        except ApiError as e:
            logger.warn("Failed to merge: %s", e.response['json']['message'])
            self.bot.head.comment(self.LGTM_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention='@' + self.bot.head.author,
                message="I can't merge: `%s`" % (
                    e.response['json']['message']
                ),
            ))
        else:
            logger.warn("Merged!")
            self.bot.head.comment(self.LGTM_COMMENT % dict(
                emoji=random.choice((
                    ':smiley:', ':sunglasses:', ':thumbup:',
                    ':ok_hand:', ':surfer:', ':white_check_mark:',
                )),
                mention=', '.join(sorted(set([
                    '@' + l.author for l in lgtms
                ]))),
                message="merged %s for you!" % (self.bot.head.ref),
            ))

    def skip(self, context):
        for pattern in self.bot.current['skip']:
            if pattern.match(context):
                return True
        return not match(context, self.bot.current['jobs-match'])

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
        'GHP_STATUS_LOOP': 0,
    }

    status_map = {
        # Requeue an aborted job
        'ABORTED': ('error', 'Aborted!'),
        'FAILURE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'UNSTABLE': ('failure', 'Build %(name)s failed in %(duration)s!'),
        'SUCCESS': ('success', 'Build %(name)s succeeded in %(duration)s'),
    }

    def compute_actual_status(self, build, current_status):
        target_url = current_status['target_url']
        # If no build found, this may be an old CI build, or any other
        # unconfirmed build. Retrigger.
        jenkins_status = build.get_status() if build else 'ABORTED'
        if build and jenkins_status:
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
        elif self.bot.head.project.SETTINGS.GHP_STATUS_LOOP:
            # Touch the commit status to avoid polling it for the next 5
            # minutes.
            state = 'pending'
            description = current_status['description']
            ellipsis = '...' if description.endswith('....') else '....'
            description = description.rstrip('.') + ellipsis
        else:
            # Don't touch
            return {}

        return dict(
            description=description, state=state, target_url=target_url,
        )

    def end(self):
        fivemin_ago = (
            datetime.datetime.utcnow() -
            datetime.timedelta(
                seconds=self.bot.head.project.SETTINGS.GHP_STATUS_LOOP
            )
        )

        failed_contexts = []
        for context, status in sorted(self.bot.head.get_statuses().items()):
            if status['state'] == 'success':
                continue

            # There is no build URL.
            if status['description'] in {'Backed', 'New', 'Queued'}:
                continue

            updated_at = parse_datetime(status['updated_at'])
            # Don't poll Jenkins more than each 5 min.
            if status['state'] == 'pending' and updated_at > fivemin_ago:
                logger.debug("Postpone Jenkins status polling.")
                continue

            # We mark actual failed with a bang to avoid rechecking it is
            # aborted.
            if status['description'].endswith('!'):
                continue

            if not status['target_url'].startswith(JENKINS.baseurl):
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

            new_status = self.compute_actual_status(build, status)
            if new_status:
                self.bot.head.update_statuses(context=context, **new_status)

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
# Build this PR first. Allowed only in PR description.
jenkins: urgent

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
            self.bot.current['help-mentions'].add(instruction.author)
        elif instruction == 'help-reset':
            self.bot.current['help-mentions'] = set()

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
            me=self.bot.head.project.SETTINGS.GHP_NAME,
            mentions=', '.join(sorted([
                '@' + m for m in self.bot.current['help-mentions']
            ])),
            software=self.DISTRIBUTION.project_name,
            version=self.DISTRIBUTION.version,
        )

    def answer_help(self):
        self.bot.head.comment(self.generate_comment())

    def end(self):
        if self.bot.current['help-mentions']:
            self.answer_help()


class ErrorExtension(Extension):
    ERROR_COMMENT = """
:see_no_evil: :bangbang:

Sorry %(mention)s, I don't understand what you mean by `%(instruction)s`: `%(error)s`.

See `jenkins: help` for documentation.

<!--
jenkins: reset-errors
-->
"""  # noqa

    def process_instruction(self, instruction):
        if instruction == 'reset-errors':
            self.bot.current['errors'] = []

    def end(self):
        for author, instruction, error in self.bot.current['errors']:
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
            self.bot.current['report-done'] = True

    def end(self):
        if self.bot.current['report-done']:
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
