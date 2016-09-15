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

import datetime
import inspect
import logging
import pkg_resources
import random
import re
import socket

from .bot import Extension, Error
from .github import GITHUB, ApiNotFoundError
from .jenkins import JENKINS
from .repository import ApiError, Branch, CommitStatus, PullRequest
from .settings import SETTINGS
from .utils import match, parse_datetime


logger = logging.getLogger(__name__)


class BuilderExtension(Extension):
    """
    # Selecting jobs
    jenkins:
      jobs: only*
      jobs: ['*', '-notthis*']
      jobs: ['this*', '+andthis*', '-notthis*']

    # Skipping
    jenkins: skip

    # Requeue past failed/skipped jobs
    jenkins: rebuild
    """

    DEFAULTS = {
        'jobs_match': [],
        'skip': [],
        'skip_errors': [],
        'rebuild_failed': None,
    }
    SKIP_ALL = ('.*',)
    BUILD_ALL = ['*']

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
        elif instruction == 'reset-skip-errors':
            self.current.skip_errors = []
        elif instruction == 'rebuild':
            self.current.rebuild_failed = instruction.date

    def run(self):
        for instruction, pattern, error in self.current.skip_errors:
            self.current.head.comment(body=self.ERROR_COMMENT % dict(
                mention='@' + instruction.author,
                pattern=pattern,
                error=str(error),
            ))

        for spec in self.current.job_specs.values():
            job = self.current.jobs[spec.name]
            if not job.is_enabled() or not job.push_trigger:
                self.current.skip.append(re.compile(spec.name))

            not_built = self.current.head.filter_not_built_contexts(
                job.list_contexts(spec),
                rebuild_failed=self.current.rebuild_failed
            )

            for context in not_built:
                self.current.head.maybe_update_status(
                    self.status_for_new_context(job, context),
                )

            queued_contexts = [c for c in not_built if not self.skip(c)]
            if queued_contexts and self.bot.queue_empty:
                try:
                    job.build(self.current.head, spec, queued_contexts)
                except Exception as e:
                    logger.exception("Failed to queue job %s: %s.", job, e)
                    for context in queued_contexts:
                        self.current.head.maybe_update_status(CommitStatus(
                            context=context, state='error',
                            description='Failed to queue job.',
                            target_url=job.baseurl,
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


class CreateJobsExtension(Extension):
    stage = '00'

    SETTINGS = {
        'JOBS_COMMAND': 'jenkins-yml-runner',
        # Jenkins credentials used to clone
        'JOBS_CREDENTIALS': None,
        # Jenkins node/label
        'JOBS_NODE': 'yml',
    }

    JOB_ERROR_COMMENT = """\
Failed to create or update Jenkins job `%(name)s`.

```
%(error)s
%(detail)s
```
"""

    def run(self):
        head = self.current.head

        try:
            jenkins_yml = GITHUB.fetch_file_contents(
                head.repository, 'jenkins.yml', ref=head.ref,
            )
            logger.debug("Loading jenkins.yml.")
        except ApiNotFoundError:
            jenkins_yml = None

        defaults = dict(
            node=SETTINGS.JOBS_NODE,
            command=SETTINGS.JOBS_COMMAND,
            github_repository=head.repository.url,
            scm_credentials=SETTINGS.JOBS_CREDENTIALS,
            set_commit_status=not SETTINGS.DRY_RUN,
        )

        self.current.job_specs = head.repository.list_job_specs(
            jenkins_yml, defaults,
        )
        self.current.jobs = {job.name: job for job in head.repository.jobs}

        for spec in self.current.job_specs.values():
            if spec.name in self.current.jobs:
                current_job = self.current.jobs[spec.name]
                if not current_job.is_enabled():
                    continue

                if current_job.spec.contains(spec):
                    continue

                jenkins_spec = current_job.spec.merge(spec)
                executer = JENKINS.update_job
            else:
                jenkins_spec = spec
                executer = JENKINS.create_job

            try:
                job = executer(jenkins_spec)
            except Exception as e:
                detail = (
                    e.args[0]
                    .replace('\\n', '\n')
                    .replace('\\t', '\t')
                )
                logger.error(
                    "Failed to manage job %r:\n%s", spec.name, detail
                )
                self.current.errors.append(Error(
                    self.JOB_ERROR_COMMENT % dict(
                        name=spec.name, error=e, detail=detail,
                    ),
                    self.current.commit_date,
                ))
            else:
                if job:
                    self.current.jobs[spec.name] = job

        head.repository.jobs = list(self.current.jobs.values())

        for job in self.current.jobs.values():
            if job.name not in self.current.job_specs:
                logger.debug("Using Jenkins job spec for %s.", job)
                self.current.job_specs[job.name] = job.spec


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
    stage = '20'

    SETTINGS = {
        'STATUS_LOOP': 0,
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
        elif self.current.head.repository.SETTINGS.STATUS_LOOP:
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
        fivemin_ago = (
            datetime.datetime.utcnow() -
            datetime.timedelta(
                seconds=self.current.head.repository.SETTINGS.STATUS_LOOP
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
    DISTRIBUTION = pkg_resources.get_distribution('jenkins-epo')
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
        for ext in self.bot.extensions:
            doc = ext.__class__.__doc__
            if not doc:
                continue
            docs.append(inspect.cleandoc(doc))
        help_ = '\n\n'.join(docs)
        return self.HELP % dict(
            extensions=','.join(sorted(self.bot.extensions_map.keys())),
            help=help_,
            host=socket.getfqdn(),
            me=self.current.head.repository.SETTINGS.NAME,
            mentions=', '.join(sorted([
                '@' + m for m in self.current.help_mentions
            ])),
            software=self.DISTRIBUTION.project_name,
            version=self.DISTRIBUTION.version,
        )

    def run(self):
        if self.current.help_mentions:
            self.current.head.comment(body=self.generate_comment())


class ErrorExtension(Extension):
    stage = '99'

    ERROR_COMMENT = """
%(emoji)s

%(error)s

<!--
jenkins: reset-errors
-->
"""  # noqa

    def process_instruction(self, instruction):
        if instruction == 'reset-errors':
            self.current.errors = [
                e for e in self.current.errors
                if e.date > instruction.date
            ]

    def run(self):
        for error in self.current.errors:
            self.current.head.comment(body=self.ERROR_COMMENT % dict(
                emoji=random.choice((
                    ':see_no_evil:', ':bangbang:', ':confused:',
                )),
                error=error.body,
            ))


class MergerExtension(Extension):
    """
    # Acknowledge for auto-merge
    jenkins: opm
    """

    stage = '90'

    DEFAULTS = {
        'lgtm': {},
        'lgtm_denied': [],
        'lgtm_processed': None,
        'merge_failed': None,
    }
    SETTINGS = {
        'LGTM_AUTHOR': False,
        'LGTM_QUORUM': 1,
    }

    LGTM_COMMENT = """
%(mention)s, %(message)s %(emoji)s

<!--
jenkins: lgtm-processed
-->
"""

    def begin(self):
        super(MergerExtension, self).begin()

        if isinstance(self.current.head, PullRequest):
            # Initialize LGTM processing
            self.current.lgtm_processed = parse_datetime(
                self.current.head.payload['created_at']
            )
            self.current.is_behind = self.current.head.is_behind()

    def process_instruction(self, instruction):
        if instruction in {'lgtm', 'merge', 'opm'}:
            self.process_lgtm(instruction)
        elif instruction == 'lgtm-processed':
            self.current.lgtm_denied[:] = []
            self.current.lgtm_processed = instruction.date
        elif instruction == 'merge-failed':
            if instruction.date > self.current.commit_date:
                self.current.merge_failed = instruction.date

    def process_lgtm(self, lgtm):
        if not hasattr(self.current.head, 'merge'):
            return logger.debug("LGTM on a non PR. Weird!")

        if self.current.is_behind:
            return logger.debug("Skip LGTM on outdated PR.")

        if lgtm.date < self.current.commit_date:
            return logger.debug("Skip outdated LGTM.")

        if lgtm.author in self.current.SETTINGS.REVIEWERS:
            logger.info("Accept @%s as reviewer.", lgtm.author)
            self.current.lgtm[lgtm.author] = lgtm
        else:
            logger.info("Refuse LGTM from @%s.", lgtm.author)
            self.current.lgtm_denied.append(lgtm)

    def check_lgtms(self):
        lgtms = self.current.lgtm
        if not lgtms:
            return

        if len(lgtms) < self.current.SETTINGS.LGTM_QUORUM:
            return logger.debug("Missing LGTMs quorum. Skipping.")

        if self.current.SETTINGS.LGTM_AUTHOR:
            self_lgtm = self.current.head.author in lgtms
            if not self_lgtm:
                return logger.debug("Author's LGTM missing. Skipping.")
        return True

    def check_statuses(self):
        unsuccess = {
            k: v for k, v in self.current.statuses.items()
            if v['state'] != 'success'
        }
        return not unsuccess

    def run(self):
        denied = {i.author for i in self.current.lgtm_denied}
        if denied:
            self.current.head.comment(body=self.LGTM_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention=', '.join(sorted(['@' + a for a in denied])),
                message="you're not allowed to acknowledge PR",
            ))

        if not self.check_lgtms():
            return
        reviewers = sorted(self.current.lgtm)
        logger.debug("Accepted LGTMs from %s.", ', '.join(reviewers))

        if not self.check_statuses():
            return logger.debug("PR not green. Postpone merge.")

        if self.current.merge_failed:
            return logger.debug("Merge already failed. Skipping.")

        try:
            self.current.head.merge()
        except ApiError as e:
            logger.warn("Failed to merge: %s", e.response['json']['message'])
            self.current.head.comment(body=self.LGTM_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention='@' + self.current.head.author,
                message="I can't merge: `%s`" % (
                    e.response['json']['message']
                ),
            ))
        else:
            logger.warn("Merged %s!", self.current.head.ref)


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

        self.current.head.comment(body=self.COMMENT_TEMPLATE % dict(
            issue=issue['number']
        ))
