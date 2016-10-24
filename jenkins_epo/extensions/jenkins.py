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
import logging
import re

from jenkins_yml import Job as JobSpec
from jenkinsapi.custom_exceptions import UnknownJob

from ..bot import Extension, Error
from ..github import GITHUB, ApiNotFoundError
from ..jenkins import JENKINS
from ..repository import CommitStatus
from ..settings import SETTINGS
from ..utils import match


logger = logging.getLogger(__name__)


class JenkinsExtension(Extension):
    def is_enabled(self, settings):
        return bool(settings.JENKINS_URL)


class BuilderExtension(JenkinsExtension):
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

    def is_queue_empty(self):
        if self.current.SETTINGS.ALWAYS_QUEUE:
            logger.info("Ignoring queue status. New jobs will be queued.")
            return True

        return JENKINS.is_queue_empty()

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
            queue_empty = self.is_queue_empty()
            toqueue_contexts = []
            for context in not_built:
                new_status = self.current.last_commit.maybe_update_status(
                    self.status_for_new_context(job, context, queue_empty),
                )
                if new_status.get('description') == 'Queued':
                    toqueue_contexts.append(context)

            if toqueue_contexts and queue_empty:
                try:
                    job.build(self.current.head, spec, toqueue_contexts)
                except Exception as e:
                    logger.exception("Failed to queue job %s: %s.", job, e)
                    for context in toqueue_contexts:
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

    def status_for_new_context(self, job, context, queue_empty):
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
            queued = queue_empty or already_queued
            new_status.update({
                'description': 'Queued' if queued else 'Backed',
                'state': 'pending',
            })
        return new_status


class CancellerExtension(JenkinsExtension):
    stage = '20'

    def iter_pending_status(self, payload):
        for i, commit in enumerate(self.current.head.process_commits(payload)):
            commit_payload = commit.fetch_statuses()
            statuses = commit.process_statuses(commit_payload)
            for context, status in statuses.items():
                if not status.get('target_url'):
                    continue
                if not status['target_url'].startswith(JENKINS.baseurl):
                    continue
                if status['state'] != 'pending':
                    continue
                yield commit, status, i == 0

    def run(self):
        payload = self.current.head.fetch_previous_commits()
        for commit, status, head in self.iter_pending_status(payload):
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
        self.current.last_commit = self.current.head.last_commit
        self.current.statuses = self.current.last_commit.statuses


class CreateJobsExtension(JenkinsExtension):
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


class StagesExtension(JenkinsExtension):
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
