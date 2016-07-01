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

import datetime
import inspect
import logging
import pkg_resources
import random
import re
import socket

from .bot import Extension
from .jenkins import JENKINS
from .repository import ApiError, Branch, CommitStatus, PullRequest
from .utils import match, parse_datetime
from . import io


logger = logging.getLogger(__name__)


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
        'jobs_match': [],
        'lgtm': [],
        'lgtm_processed': None,
        'skip': [],
        'skip_errors': [],
        'rebuild_failed': None,
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

        if isinstance(self.current.head, PullRequest):
            # Initialize LGTM processing
            self.current.lgtm_processed = parse_datetime(
                self.current.head.payload['created_at']
            )

    def process_instruction(self, instruction):
        if instruction == 'skip':
            patterns = instruction.args
            if isinstance(patterns, str):
                patterns = [patterns]
            patterns = patterns or self.SKIP_ALL
            self.current.skip = skip = []
            self.current.skip_errors = errors = []
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

            self.current.jobs_match = patterns
        elif instruction in {'lgtm', 'merge', 'opm'}:
            if hasattr(self.current.head, 'merge'):
                if not self.current.lgtm:
                    logger.debug("LGTM incoming.")
                self.current.lgtm.append(instruction)
        elif instruction == 'lgtm-processed':
            self.current.lgtm_processed = instruction.date
        elif instruction == 'reset-skip-errors':
            self.current.skip_errors = []
        elif instruction == 'rebuild':
            self.current.rebuild_failed = instruction.date

    def run(self):
        if False:
            yield None

        for instruction, pattern, error in self.current.skip_errors:
            self.current.head.comment(self.ERROR_COMMENT % dict(
                mention='@' + instruction.author,
                pattern=pattern,
                error=str(error),
            ))

        for job in self.current.jobs:
            not_built = self.current.head.filter_not_built_contexts(
                job.list_contexts(),
                rebuild_failed=self.current.rebuild_failed
            )

            for context in not_built:
                self.current.head.maybe_update_status(
                    self.status_for_new_context(job, context),
                )

            queued_contexts = [c for c in not_built if not self.skip(c)]
            if queued_contexts and self.bot.queue_empty:
                try:
                    job.build(self.current.head, queued_contexts)
                except Exception as e:
                    logger.warn("Failed to queue job %s: %s.", job, e)
                    for context in queued_contexts:
                        self.current.head.maybe_update_status(CommitStatus(
                            context=context, state='error',
                            description='Failed to queue job.',
                            target_url=job.baseurl,
                        ))

        self.maybe_merge()

    def check_lgtm(self):
        lgtms = self.current.lgtm[:]
        if not lgtms:
            return

        logger.debug("Validating LGTMs.")
        processed_date = self.current.lgtm_processed

        lgtmers = {i.author for i in lgtms}
        new_refused = set()
        for author in list(lgtmers):
            if author in self.current.head.repository.SETTINGS.GHP_REVIEWERS:
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
            self.current.head.comment(self.LGTM_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention=', '.join(sorted(['@' + a for a in new_refused])),
                message="you're not allowed to acknowledge PR",
            ))

        lgtms = [i for i in lgtms if i.author in lgtmers]
        if not lgtms:
            return logger.debug("No legal LGTMs. Skipping.")

        commit_date = parse_datetime(
            self.current.head.commit['committer']['date']
        )
        outdated_lgtm = [l for l in lgtms if l.date < commit_date]
        if outdated_lgtm:
            logger.debug("Some LGTMs are outdated.")
        lgtms = list(set(lgtms) - set(outdated_lgtm))

        lgtmers = {i.author for i in lgtms}
        if len(lgtms) > len(lgtmers):
            logger.debug("Deduplicate LGTMs.")
            lgtms = [
                [l for l in lgtms if l.author == a][0] for a in lgtmers
            ]

        if len(lgtms) < self.current.head.repository.SETTINGS.GHP_LGTM_QUORUM:
            return logger.debug("Missing LGTMs quorum. Skipping.")

        if self.current.head.repository.SETTINGS.GHP_LGTM_AUTHOR:
            self_lgtm = self.current.head.author in {i.author for i in lgtms}
            if not self_lgtm:
                return logger.debug("Author's LGTM missing. Skipping.")

        logger.debug(
            "Accepted LGTMs from %s.",
            ', '.join([l.author for l in lgtms])
        )

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

        unsuccess = {
            k: v for k, v in self.current.statuses.items()
            if v['state'] != 'success'
        }
        if unsuccess:
            return logger.debug("PR not green. Postpone merge.")

        if self.current.head.is_behind():
            logger.debug("Base updated since LGTM. Skipping merge.")
            unprocessed_lgtms = [
                l for l in lgtms
                if l.date > self.current.lgtm_processed
            ]
            if unprocessed_lgtms:
                self.current.head.comment(self.LGTM_COMMENT % dict(
                    emoji=random.choice((':confused:', ':disappointed:')),
                    mention='@' + self.current.head.author,
                    message=(
                        "%(base)s has been updated and this PR is now behind. "
                        "I don't merge behind PR." % dict(
                            base=self.current.head.payload['base']['label'],
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
            self.current.head.merge()
        except ApiError as e:
            logger.warn("Failed to merge: %s", e.response['json']['message'])
            self.current.head.comment(self.LGTM_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention='@' + self.current.head.author,
                message="I can't merge: `%s`" % (
                    e.response['json']['message']
                ),
            ))
        else:
            logger.warn("Merged!")
            self.current.head.comment(self.LGTM_COMMENT % dict(
                emoji=random.choice((
                    ':smiley:', ':sunglasses:', ':thumbup:',
                    ':ok_hand:', ':surfer:', ':white_check_mark:',
                )),
                mention=', '.join(sorted(set([
                    '@' + l.author for l in lgtms
                ]))),
                message="merged %s for you!" % (self.current.head.ref),
            ))

    def skip(self, context):
        for pattern in self.current.skip:
            if pattern.match(context):
                return True
        return not match(context, self.current.jobs_match)

    def status_for_new_context(self, job, context):
        new_status = CommitStatus(target_url=job.baseurl, context=context)
        if self.skip(context):
            new_status.update({
                'description': 'Skipped',
                'state': 'success',
            })
        else:
            current_status = self.current.statuses.get(context, {})
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
        # If no build found, this may be an old CI build, or any other
        # unconfirmed build. Retrigger.
        jenkins_status = build.get_status() if build else 'ABORTED'
        if build and jenkins_status:
            state, description = self.status_map[jenkins_status]
            if description != 'Backed':
                duration = format_duration(build._data['duration'])
                try:
                    description = description % dict(
                        name=build._data['displayName'],
                        duration=duration,
                    )
                except TypeError:
                    pass
        elif self.current.head.repository.SETTINGS.GHP_STATUS_LOOP:
            # Touch the commit status to avoid polling it for the next 5
            # minutes.
            state = 'pending'
            description = current_status['description']
            ellipsis = '...' if description.endswith('....') else '....'
            description = description.rstrip('.') + ellipsis
        else:
            # Don't touch
            return CommitStatus()

        return CommitStatus(
            current_status, description=description, state=state,
        )

    def run(self):
        if False:
            yield None

        fivemin_ago = (
            datetime.datetime.utcnow() -
            datetime.timedelta(
                seconds=self.current.head.repository.SETTINGS.GHP_STATUS_LOOP
            )
        )

        failed_contexts = []
        for context, status in self.current.statuses.items():
            if status['state'] == 'success':
                continue

            # There is no build URL.
            if status['description'] in {'Backed', 'New', 'Queued'}:
                continue

            # Don't poll Jenkins more than each 5 min.
            old = status['updated_at'] > fivemin_ago
            if status['state'] == 'pending' and old:
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
                self.current.head.maybe_update_status(new_status)

        if failed_contexts:
            logger.warn(
                "Failed to get actual build status for contexts: %s",
                failed_contexts
            )


class HelpExtension(Extension):
    DEFAULTS = {
        'help_mentions': set(),
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
            self.current.help_mentions.add(instruction.author)
        elif instruction == 'help-reset':
            self.current.help_mentions = set()

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
            me=self.current.head.repository.SETTINGS.GHP_NAME,
            mentions=', '.join(sorted([
                '@' + m for m in self.current.help_mentions
            ])),
            software=self.DISTRIBUTION.project_name,
            version=self.DISTRIBUTION.version,
        )

    def run(self):
        if self.current.help_mentions:
            yield io.WriteComment(self.generate_comment())


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
            self.current.errors = []

    def run(self):
        for author, instruction, error in self.current.errors:
            yield io.WriteComment(body=self.ERROR_COMMENT % dict(
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
        'report_done': False,
    }

    def process_instruction(self, instruction):
        if instruction == 'report-done':
            self.current.report_done = True

    def run(self):
        if False:
            yield None

        if self.current.report_done:
            return

        if not isinstance(self.current.head, Branch):
            return

        errored = [
            s for s in self.current.statuses.values()
            if s['state'] == 'failure'
        ]
        if not errored:
            return

        branch_name = self.current.head.ref[len('refs/heads/'):]
        builds = '- ' + '\n- '.join([s['target_url'] for s in errored])
        issue = self.current.head.repository.report_issue(
            title="%s is broken" % (branch_name,),
            body=self.ISSUE_TEMPLATE % dict(
                abbrev=self.current.head.sha[:7],
                branch=branch_name,
                builds=builds,
                sha=self.current.head.sha,
                ref=self.current.head.ref,
            )
        )

        yield io.WriteComment(body=self.COMMENT_TEMPLATE % dict(
            issue=issue['number']
        ))
