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

from collections import OrderedDict
import inspect
import logging
import pkg_resources
import random
import re
import socket

from jenkins_yml import Job as JobSpec
from jenkinsapi.custom_exceptions import UnknownJob

from .bot import Extension, Error
from .github import GITHUB, ApiNotFoundError
from .jenkins import JENKINS
from .repository import ApiError, Branch, CommitStatus
from .settings import SETTINGS
from .utils import match, parse_patterns


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
            if spec.config.get('periodic'):
                continue

            branches = spec.config.get('only', '*')
            if isinstance(branches, str):
                branches = [branches]
            if not match(self.current.head.ref[len('refs/heads/'):], branches):
                logger.info("Skipping job %s for this branch.", spec)
                continue

            logger.debug("Processing job %s.", spec)
            job = self.current.jobs[spec.name]
            not_built = self.current.last_commit.filter_not_built_contexts(
                job.list_contexts(spec),
                rebuild_failed=self.current.rebuild_failed
            )
            queued_contexts = []
            for context in not_built:
                new_status = self.current.last_commit.maybe_update_status(
                    self.status_for_new_context(job, context),
                )
                if new_status['description'] == 'Queued':
                    queued_contexts.append(context)

            if queued_contexts and self.bot.queue_empty:
                try:
                    job.build(self.current.head, spec, queued_contexts)
                except Exception as e:
                    logger.exception("Failed to queue job %s: %s.", job, e)
                    for context in queued_contexts:
                        self.current.last_commit.maybe_update_status(
                            CommitStatus(
                                context=context, state='error',
                                description='Failed to queue job.',
                                target_url=job.baseurl,
                            )
                        )

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
        elif not job.is_enabled():
            new_status.update({
                'description': 'Disabled on Jenkins.',
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


class CancellerExtension(Extension):
    stage = '20'

    def iter_pending_status(self):
        payload = self.current.head.fetch_previous_commits()
        head = True
        for commit in self.current.head.process_commits(payload):
            payload = commit.fetch_statuses()
            statuses = commit.process_statuses(payload)
            for context, status in statuses.items():
                if not status.get('target_url'):
                    continue
                if not status['target_url'].startswith(JENKINS.baseurl):
                    continue
                if status['state'] != 'pending':
                    continue
                yield commit, status, head
            head = False

    def run(self):
        for commit, status, head in self.iter_pending_status():
            logger.debug("Query Jenkins %s status for %s.", status, commit)
            try:
                build = JENKINS.get_build_from_url(status['target_url'])
            except Exception as e:
                logger.debug(
                    "Failed to get pending build status for contexts: %s: %s",
                    e.__class__.__name__, e,
                )
                build = None

            if not head and build and build.is_running():
                logger.warn("Cancelling %s.", build)
                build.stop()
                new_status = status.__class__(
                    status, state='error', description='Cancelled after push.'
                )
            else:
                new_status = status.from_build(build)
            commit.maybe_update_status(new_status)


class CreateJobsExtension(Extension):
    """
    jenkins: refresh-jobs  # Refresh job definition on Jenkins.
    """

    stage = '00'

    DEFAULTS = {
        'jobs': {},
        'job_specs': {},
        'refresh_jobs': {},
    }

    SETTINGS = {
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

    def process_instruction(self, instruction):
        if instruction == 'refresh-jobs':
            self.current.refresh_jobs = instruction.date

    def list_job_specs(self, jenkins_yml=None):
        defaults = dict(
            node=SETTINGS.JOBS_NODE,
            github_repository=self.current.head.repository.url,
            scm_credentials=SETTINGS.JOBS_CREDENTIALS,
            set_commit_status=not SETTINGS.DRY_RUN,
        )

        jenkins_yml = jenkins_yml or '{}'
        jobs = {}
        for job in JobSpec.parse_all(jenkins_yml, defaults=defaults):
            job.repository = self.current.head.repository
            jobs[job.name] = job

        return jobs

    def process_job_specs(self):
        for spec in self.current.job_specs.values():
            current_job = self.current.jobs.get(spec.name)
            if not current_job:
                yield JENKINS.create_job, spec
                continue

            update = False
            if self.current.refresh_jobs:
                update = (
                    not current_job.updated_at or
                    self.current.refresh_jobs >= current_job.updated_at
                )

            if not current_job.spec.contains(spec):
                spec = current_job.spec.merge(spec)
                update = True

            if update:
                yield JENKINS.update_job, spec

    def run(self):
        head = self.current.head

        try:
            jenkins_yml = GITHUB.fetch_file_contents(
                head.repository, 'jenkins.yml', ref=head.ref,
            )
            logger.debug("Loading jenkins.yml.")
        except ApiNotFoundError:
            jenkins_yml = None

        self.current.job_specs = self.list_job_specs(jenkins_yml)
        self.current.jobs = head.repository.jobs

        for name in self.current.job_specs:
            if name in self.current.jobs:
                continue
            try:
                self.current.jobs[name] = JENKINS.get_job(name)
            except UnknownJob:
                pass

        for action, spec in self.process_job_specs():
            job = None
            try:
                job = action(spec)
            except Exception as e:
                self.current.errors.append(self.process_error(spec, e))

            if not job:
                continue

            self.current.jobs[job.name] = job

            if spec.config.get('periodic'):
                self.current.last_commit.push_status(CommitStatus(
                    context=job.name, state='success',
                    target_url=job.baseurl, description='Created!',
                ))

    def process_error(self, spec, e):
        detail = (
            e.args[0]
            .replace('\\n', '\n')
            .replace('\\t', '\t')
        )
        logger.error(
            "Failed to manage job %r:\n%s", spec.name, detail
        )
        return Error(
            self.JOB_ERROR_COMMENT % dict(
                name=spec.name, error=e, detail=detail,
            ),
            self.current.last_commit.date,
        )


class Stage(object):
    @classmethod
    def factory(cls, entry):
        if isinstance(entry, str):
            entry = dict(name=entry)
        return cls(**entry)

    def __init__(self, name, external=None, **kw):
        self.name = name
        self.job_specs = []
        self.external_contextes = external or []
        self.statuses = []

    def __str__(self):
        return self.name

    def is_complete(self, jobs, statuses):
        for context in self.external_contextes:
            state = statuses.get(context, {}).get('state')
            if state != 'success':
                logger.debug("Missing context %s for stage %s.", context, self)
                return False

        for spec in self.job_specs:
            job = jobs[spec.name]
            for context in job.list_contexts(spec):
                state = statuses.get(context, {}).get('state')
                if state != 'success':
                    logger.debug("Missing job %s for stage %s.", spec, self)
                    return False
        return True


class StagesExtension(Extension):
    stage = '30'

    SETTINGS = {
        'STAGES': ['build', 'test', 'deploy'],
    }

    def run(self):
        stages = [Stage.factory(i) for i in self.current.SETTINGS.STAGES]
        # First, group jobs by stages
        self.current.stages = stages = OrderedDict(
            [(s.name, s) for s in stages],
        )
        default_stage = 'test' if 'test' in stages else list(stages.keys())[0]
        for spec in self.current.job_specs.values():
            if spec.config.get('periodic') and not spec.config.get('stage'):
                logger.debug("Skipping %s with no explicit stage.", spec)
                continue
            stage = spec.config.get('stage', default_stage)
            stages[stage].job_specs.append(spec)

        # Search current stage to build.
        for stage in stages.values():
            if not stage.is_complete(self.current.jobs, self.current.statuses):
                logger.info("Current stage is %s.", stage)
                break
        else:
            logger.info("All stages completed.")

        self.current.current_stage = stage
        # Filter job specs to the current stage ones.
        self.current.job_specs = {j.name: j for j in stage.job_specs}


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
        'opm': None,
        'opm_denied': [],
        'opm_processed': None,
        'last_merge_error': None,
    }

    SETTINGS = {
        'WIP_TITLE': 'wip*,[wip*',
    }

    OPM_COMMENT = """
%(mention)s, %(message)s %(emoji)s

<!--
jenkins: opm-processed
-->
"""

    MERGE_ERROR_COMMENT = """
%(mention)s, %(message)s %(emoji)s

<!--
jenkins: {last-merge-error: %(message)r}
-->
"""

    def begin(self):
        super(MergerExtension, self).begin()

        if hasattr(self.current.head, 'merge'):
            patterns = parse_patterns(self.current.SETTINGS.WIP_TITLE.lower())
            title = self.current.head.payload['title'].lower()
            self.current.wip = match(title, patterns)
            if self.current.wip:
                logger.debug("%s is a WIP.", self.current.head)

    def process_instruction(self, instruction):
        if instruction in {'lgtm', 'merge', 'opm'}:
            self.process_opm(instruction)
        elif instruction in {'lgtm-processed', 'opm-processed'}:
            self.current.opm_denied[:] = []
            self.current.opm_processed = instruction
        elif instruction == 'last-merge-error':
            self.current.last_merge_error = instruction

    def process_opm(self, opm):
        if not hasattr(self.current.head, 'merge'):
            return logger.debug("OPM on a non PR. Weird!")

        if opm.date < self.current.last_commit.date:
            return logger.debug("Skip outdated OPM.")

        if opm.author in self.current.SETTINGS.REVIEWERS:
            logger.info("Accept @%s as reviewer.", opm.author)
            self.current.opm = opm
        else:
            logger.info("Refuse OPM from @%s.", opm.author)
            self.current.opm_denied.append(opm)

    def run(self):
        denied = {i.author for i in self.current.opm_denied}
        if denied:
            self.current.head.comment(body=self.OPM_COMMENT % dict(
                emoji=random.choice((
                    ':confused:', ':cry:', ':disappointed:', ':frowning:',
                    ':scream:',
                )),
                mention=', '.join(sorted(['@' + a for a in denied])),
                message="you're not allowed to acknowledge PR",
            ))

        if not self.current.opm:
            return
        logger.debug("Accept to merge for @%s.", self.current.opm.author)

        if self.current.wip:
            logger.info("Not merging WIP PR.")
            proc = self.current.opm_processed
            if proc and proc.date > self.current.opm.date:
                return

            self.current.head.comment(body=self.OPM_COMMENT % dict(
                emoji=random.choice((
                    ':confused:', ':hushed:', ':no_mouth:', ':open_mouth:',
                )),
                mention='@' + self.current.opm.author,
                message="this PR is still WIP",
            ))
            return

        status = self.current.last_commit.fetch_combined_status()
        if status['state'] != 'success':
            return logger.debug("PR not green. Postpone merge.")

        try:
            self.current.head.merge()
        except ApiError as e:
            error = e.response['json']['message']
            if self.current.last_merge_error:
                last_error = self.current.last_merge_error.args
                if error == last_error:
                    return logger.debug("Merge still failing: %s", error)

            logger.warn("Failed to merge: %s", error)
            self.current.head.comment(body=self.MERGE_ERROR_COMMENT % dict(
                emoji=random.choice((':confused:', ':disappointed:')),
                mention='@' + self.current.opm.author, message=error,
            ))
        else:
            logger.warn("Merged %s!", self.current.head)
            self.current.head.delete_branch()


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
