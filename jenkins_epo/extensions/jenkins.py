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

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta
import logging
import re

from jenkinsapi.custom_exceptions import UnknownJob

from ..bot import Extension, Error, SkipHead
from ..jenkins import JENKINS
from ..repository import Commit, CommitStatus
from ..utils import match, switch_coro


logger = logging.getLogger(__name__)


class JenkinsExtension(Extension):
    def is_enabled(self, settings):
        return bool(settings.JENKINS_URL)


class BackedExtension(JenkinsExtension):
    stage = '20'

    @asyncio.coroutine
    def run(self):
        missing_contextes = [
            c
            for spec in self.current.job_specs.values()
            for c in self.current.jobs[spec.name].list_contexts(spec)
            if c not in self.current.statuses
        ]

        for context in missing_contextes:
            self.current.last_commit.maybe_update_status(dict(
                context=context,
                description='Backed',
                state='pending',
            ))
            yield from switch_coro()


class BuilderExtension(JenkinsExtension):
    """
    jenkins: rebuild  # Retry failed jobs
    """

    DEFAULTS = {
        'rebuild_failed': None,
    }

    def process_instruction(self, instruction):
        if instruction == 'rebuild':
            logger.info("Retrying jobs failed before %s.", instruction.date)
            self.current.rebuild_failed = instruction.date

    @asyncio.coroutine
    def run(self):
        for spec in self.current.job_specs.values():
            logger.debug("Processing %s.", spec)
            job = self.current.jobs[spec.name]
            not_built = self.current.last_commit.filter_not_built_contexts(
                job.list_contexts(spec),
                rebuild_failed=self.current.rebuild_failed
            )
            queue_empty = JENKINS.is_queue_empty()
            toqueue_contexts = []
            for context in not_built:
                logger.debug("Computing new status for %s.", spec)
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

    def status_for_new_context(self, job, context, queue_empty):
        new_status = CommitStatus(target_url=job.baseurl, context=context)
        if not job.is_enabled():
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
    stage = '49'

    def aggregate_queues(self, cancel_queue, poll_queue):
        for commit, status in cancel_queue:
            yield commit, status, True
        for commit, status in poll_queue:
            yield commit, status, False

    @asyncio.coroutine
    def run(self):
        aggregated_queue = self.aggregate_queues(
            self.current.cancel_queue, self.current.poll_queue
        )

        logger.info("Polling job statuses on Jenkins.")
        for commit, status, cancel in aggregated_queue:
            if not str(status['target_url']).startswith(JENKINS.baseurl):
                continue

            logger.debug("Query Jenkins %s status for %s.", status, commit)
            try:
                build = JENKINS.get_build_from_url(status['target_url'])
                build.poll()
            except Exception as e:
                logger.debug(
                    "Failed to get pending build status for contexts: %s: %s",
                    e.__class__.__name__, e,
                )
                build = None

            if not build:
                new_status = status.__class__(
                    status, state='error', description="Build not on Jenkins."
                )
            elif cancel and build.is_running():
                if self.current.SETTINGS.DRY_RUN:
                    logger.warn("Would cancelling %s.", build)
                else:
                    logger.warn("Cancelling %s.", build)
                    build.stop()
                new_status = status.__class__(
                    status, state='error', description='Cancelled after push.'
                )
            else:
                new_status = status.from_build(build)

            commit.maybe_update_status(new_status)


class CreateJobsExtension(JenkinsExtension):
    """
    jenkins: refresh-jobs  # Refresh job definition on Jenkins.
    """

    stage = '05'

    DEFAULTS = {
        'jobs': {},
        'job_specs': {},
        'refresh_jobs': {},
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

    @asyncio.coroutine
    def fetch_job(self, name):
        if name in self.current.jobs:
            return
        try:
            self.current.jobs[name] = yield from JENKINS.aget_job(name)
        except UnknownJob:
            pass

    @asyncio.coroutine
    def run(self):
        logger.info("Fetching jobs from Jenkins.")
        loop = asyncio.get_event_loop()
        tasks = [
            loop.create_task(self.fetch_job(name))
            for name in self.current.job_specs
        ]
        yield from asyncio.gather(*tasks)

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


class PollExtension(JenkinsExtension):
    stage = '30'

    ref_re = re.compile(r'.*origin/(?P<ref>.*)')

    def compute_build_ref_and_sha(self, job, build):
        try:
            jenkins_fullref = build.get_revision_branch()[0]['name']
        except IndexError:
            for action in build._data['actions']:
                if 'parameters' in action:
                    break
            else:
                return
            for parameter in action['parameters']:
                if parameter['name'] == job.revision_param:
                    break
            else:
                return
            return (
                parameter['value'][len('refs/heads/'):],
                self.current.last_commit.sha
            )
        else:
            match = self.ref_re.match(jenkins_fullref)
            if not match:
                return
            return (
                match.group('ref'),
                build.get_revision()
            )

    def iter_preset_statuses(self, contextes, build):
        for context in contextes:
            default_status = CommitStatus(
                context=context, state='pending', description='Backed',
            )
            status = self.current.statuses.get(
                context, default_status,
            )
            new_url = status.get('target_url') == build.baseurl
            if status.is_queueable or new_url:
                status = status.from_build(build)
                yield status

    def is_build_old(self, build):
        now = datetime.now()
        maxage = timedelta(hours=2)
        seconds = build._data['timestamp'] / 1000.
        build_date = datetime.fromtimestamp(seconds)
        build_age = now - build_date
        if build_date > now:
            logger.warning(
                "Build %s in the future. Is timezone correct?", build
            )
            return False
        return build_age > maxage

    @asyncio.coroutine
    def poll_job(self, spec):
        job = self.current.jobs[spec.name]
        payload = yield from job.fetch_builds()
        contextes = job.list_contexts(spec)
        for build in job.process_builds(payload):
            if self.is_build_old(build):
                break

            if not build._data['building']:
                continue

            try:
                build_ref, build_sha = (
                    self.compute_build_ref_and_sha(job, build)
                )
            except TypeError:
                logger.debug(
                    "Can't infer build ref and sha for %s.", build,
                )
                continue

            if build_ref != self.current.head.ref:
                continue

            if build_sha == self.current.last_commit.sha:
                commit = self.current.last_commit
                preset_statuses = self.iter_preset_statuses(
                    contextes, build,
                )
                for status in preset_statuses:
                    logger.info(
                        "Preset pending status for %s.", status['context'],
                    )
                    commit.maybe_update_status(status)
                    yield from switch_coro()
                continue

            commit = Commit(self.current.head.repository, build_sha)
            status = CommitStatus(context=job.name).from_build(build)
            logger.info("Queuing %s for cancel.", build)
            self.current.cancel_queue.append((commit, status))
        logger.debug("Polling %s done.", spec.name)

    @asyncio.coroutine
    def run(self):
        logger.info("Polling running builds on Jenkins.")
        tasks = []
        loop = asyncio.get_event_loop()
        for name, spec in self.current.job_specs.items():
            tasks.append(
                loop.create_task(self.poll_job(spec))
            )
        yield from asyncio.gather(*tasks)


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

    def __bool__(self):
        return bool(self.job_specs or self.external_contextes)

    def __str__(self):
        return self.name

    def is_complete(self, jobs, statuses):
        for context in self.external_contextes:
            state = statuses.get(context, {}).get('state')
            if state != 'success':
                logger.debug("Missing context %s for stage %s.", context, self)
                return False

        for spec in self.job_specs:
            try:
                job = jobs[spec.name]
            except KeyError:
                continue
            for context in job.list_contexts(spec):
                state = statuses.get(context, {}).get('state')
                if state != 'success':
                    logger.debug("Missing job %s for stage %s.", spec, self)
                    return False
        return True


class StagesExtension(JenkinsExtension):
    stage = '10'

    SETTINGS = {
        'STAGES': ['build', 'test', 'deploy'],
    }

    @asyncio.coroutine
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

        stage = None
        # Search current stage to build.
        for stage in [s for s in stages.values() if bool(s)]:
            complete = stage.is_complete(
                self.current.jobs, self.current.statuses
            )
            if not complete:
                break

        if not stage:
            logger.warn("Not in any stage. Skipping.")
            raise SkipHead()

        self.current.current_stage = stage
        # Filter job specs to the current stage ones.
        current_ref = self.current.head.ref
        self.current.job_specs = {}
        for spec in stage.job_specs:
            branches = spec.config.get('branches', ['*'])
            if not isinstance(branches, list):
                branches = [branches]
            if not match(current_ref, branches):
                logger.debug("Ignore job %s on this branch.", spec)
                continue

            if spec.config.get('periodic'):
                logger.debug("Ignore periodic job %s.", spec)
                continue

            self.current.job_specs[spec.name] = spec

        logger.info(
            "Current stage is %s. Completed=%s. Jobs: %s.",
            stage, complete, ', '.join(self.current.job_specs) or 'None',
        )
