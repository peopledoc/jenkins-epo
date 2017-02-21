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
from copy import deepcopy
import datetime
import inspect
import logging
import pkg_resources
import random
import socket

from jenkins_yml.job import Job as JobSpec

from ..bot import Extension, Error, SkipHead
from ..github import GITHUB, ApiError, ApiNotFoundError
from ..jenkins import Job
from ..repository import Branch, CommitStatus
from ..settings import SETTINGS
from ..utils import deepupdate, log_context, match, parse_patterns


logger = logging.getLogger(__name__)


class AutoCancelExtension(Extension):
    stage = '30'

    @asyncio.coroutine
    def process_commit(self, commit):
        log_context(self.current.head)
        is_head = commit.sha == self.current.head.sha
        now = datetime.datetime.utcnow()
        max_age = datetime.timedelta(seconds=3600)
        age = now - commit.date
        if not is_head and age > max_age:
            return

        commit_payload = yield from commit.fetch_statuses()
        statuses = commit.process_statuses(commit_payload)
        for status in statuses.values():
            status = CommitStatus(status)
            if status.get('state') != 'pending':
                continue

            if status.is_queueable:
                continue

            if is_head:
                self.current.poll_queue.append((commit, status))
            else:
                logger.info("Queue cancel of %s on %s.", status, commit)
                self.current.cancel_queue.append((commit, status))

    @asyncio.coroutine
    def run(self):
        loop = asyncio.get_event_loop()
        tasks = [
            loop.create_task(self.process_commit(commit))
            for commit in self.current.commits
        ]
        yield from asyncio.gather(*tasks)


class HelpExtension(Extension):
    stage = '90'

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
%(help)s
```

You can mix instructions. Multiline instructions **must** be in code block.

--
*%(me)s at your service*

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

    @asyncio.coroutine
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

    DENY_COMMENT = """
%(mentions)s, sorry, I'm not allowed to obey you! %(emoji)s

<!--
jenkins: reset-denied
-->
"""  # noqa

    DEFAULTS = {
        'error_reset': None,
    }

    def process_instruction(self, instruction):
        if instruction == 'reset-errors':
            self.current.error_reset = instruction.date
        elif instruction == 'reset-denied':
            self.current.denied_instructions[:] = []

    @asyncio.coroutine
    def run(self):
        reset = self.current.error_reset
        for error in self.current.errors:
            if reset and error.date < reset:
                continue

            self.current.head.comment(body=self.ERROR_COMMENT % dict(
                emoji=random.choice((
                    ':bangbang:', ':confused:', ':grimacing:',
                    ':see_no_evil:', ':sob:',
                )),
                error=error.body,
            ))

        denied = {i.author for i in self.current.denied_instructions}
        if denied:
            self.current.head.comment(body=self.DENY_COMMENT % dict(
                mentions='@' + ', @'.join(sorted(denied)),
                emoji=random.choice((
                    ':confused:', ':cop:', ':hear_no_evil:', ':innocent:',
                    ':neutral_face:', ':scream_cat:', ':see_no_evil:',
                )),
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

    def process_opm(self, opm):
        if not hasattr(self.current.head, 'merge'):
            return logger.debug("OPM on a non PR. Weird!")

        if opm.date < self.current.last_commit.date:
            return logger.debug("Skip outdated OPM.")

        if opm.author in self.current.SETTINGS.COLLABORATORS:
            logger.info("Accept @%s as reviewer.", opm.author)
            self.current.opm = opm
        else:
            logger.info("Refuse OPM from @%s.", opm.author)
            self.current.opm_denied.append(opm)

    @asyncio.coroutine
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

        if not self.current.statuses:
            return logger.info("Not jobs reported yet. Postpone merge.")

        status = self.current.last_commit.fetch_combined_status()
        if status['state'] != 'success':
            return logger.info("PR not green. Postpone merge.")

        try:
            self.current.head.merge()
        except ApiError as e:
            error = e.response['json']['message']
            if e.response['code'] in (405, 409):
                logger.warn("Fail to merge: %s", error)
        else:
            self.current.head.delete_branch()


class OutdatedExtension(Extension):
    stage = '00'

    SETTINGS = {
        'COMMIT_MAX_WEEKS': 4,
    }

    def begin(self):
        weeks = self.current.SETTINGS.COMMIT_MAX_WEEKS
        maxage = datetime.timedelta(weeks=weeks)
        age = datetime.datetime.utcnow() - self.current.last_commit.date
        if age > maxage:
            logger.warn(
                'Skipping head older than %s weeks.',
                self.current.SETTINGS.COMMIT_MAX_WEEKS,
            )
            raise SkipHead()


class ReportExtension(Extension):
    stage = '90'

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

    @asyncio.coroutine
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

        branch_name = self.current.head.ref
        build_urls = [s['target_url'] for s in errored if s['target_url']]
        builds = '- ' + '\n- '.join(build_urls)
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


class SecurityExtension(Extension):
    """
    jenkins: allow  # Allow to build this PR.
    """
    stage = '00'

    DEFAULTS = {
        'secure': False,
        'security_feedback_processed': False,
    }

    FEEDBACK_TEMPLATE = """
Sorry %(mention)s, I'm not allowed to test your code! %(emoji)s

Please note that %(mention)s instructions before `jenkins: allow` wont be ever
interpreted! *Please repost them along allow*:

> ``` yaml
> jenkins:
>   allow:
>   jobs: app-units
> ```

<!--
jenkins: security-feedback-processed
-->
"""

    def process_instruction(self, instruction):
        if instruction.name == 'security-feedback-processed':
            self.current.security_feedback_processed = True
        elif instruction == 'allow':
            author = getattr(self.current.head, 'author', None)
            if author:
                logger.warn("Allowing EPO to test @%s's code.", author)
                self.current.SETTINGS.COLLABORATORS.append(author)
            self.current.denied_instructions[:] = [
                i for i in self.current.denied_instructions
                if i.author != author
            ]

    @asyncio.coroutine
    def run(self):
        author = getattr(self.current.head, 'author', None)

        if not author:
            # In case the extension is running on a branch
            return

        if author in self.current.SETTINGS.COLLABORATORS:
            return

        if not self.current.security_feedback_processed:
            self.current.head.comment(body=self.FEEDBACK_TEMPLATE % dict(
                emoji=random.choice((
                    ':hand:', ':no_entry_sign:', ':no_entry:',
                    ':confused:', ':cop:', ':hear_no_evil:', ':innocent:',
                    ':neutral_face:', ':scream_cat:', ':see_no_evil:',
                )),
                mention='@' + author,
            ))

        logger.warn("Skipping PR from @%s.", author)
        raise SkipHead()


class SkipExtension(Extension):
    """
    jenkins: skip  # Skip all jobs

    # Selecting jobs
    jenkins:
      jobs: only*
      jobs: ['this*', '+andthis*', '-notthis*']
    """

    stage = '30'

    DEFAULTS = {
        'jobs_match': [],
    }

    def process_instruction(self, instruction):
        if instruction == 'skip':
            self.current.jobs_match = ['!*']
        elif instruction == 'jobs':
            patterns = instruction.args
            if isinstance(patterns, str):
                patterns = [patterns]
            self.current.jobs_match = patterns

    @asyncio.coroutine
    def run(self):
        for name, spec in self.current.job_specs.items():
            job = self.current.jobs[name]
            for context in job.list_contexts(spec):
                if match(context, self.current.jobs_match):
                    continue

                status = self.current.statuses.get(context, CommitStatus())
                if status.get('state') == 'success':
                    continue

                if status.is_running:
                    self.current.cancel_queue.append(
                        (self.current.last_commit, status)
                    )

                logger.info("Skipping %s.", context)
                self.current.last_commit.maybe_update_status(CommitStatus(
                    context=context, target_url=job.baseurl,
                    state='success', description='Skipped!',
                ))


class UnskipExtension(Extension):
    stage = '09'

    DEFAULTS = {
        'jobs_match': [],
    }

    @asyncio.coroutine
    def run(self):
        for name, spec in self.current.all_job_specs.items():
            job = self.current.jobs[name]
            for context in job.list_contexts(spec):
                if not match(context, self.current.jobs_match):
                    continue

                status = self.current.statuses.get(context, CommitStatus())
                if not status.is_skipped:
                    continue

                logger.info("Unskipping %s.", context)
                self.current.last_commit.maybe_update_status(CommitStatus(
                    status, state='pending', description='Backed',
                ))


class YamlExtension(Extension):
    """
    # Ephemeral jobs parameters
    jenkins:
      parameters:
        job1:
          PARAM: value
    """
    stage = '02'

    DEFAULTS = {
        'yaml': {},
        'yaml_date': None,
    }

    SETTINGS = {
        # Jenkins credentials used to clone
        'JOBS_CREDENTIALS': None,
        # Jenkins node/label
        'JOBS_NODE': 'master',
    }

    def process_instruction(self, instruction):
        if instruction.name in {'yaml', 'yml'}:
            if not isinstance(instruction.args, dict):
                self.current.errors.append(
                    Error("YAML args is not a mapping.", instruction.date)
                )
                return
            deepupdate(self.current.yaml, instruction.args)
            self.current.yaml_date = instruction.date
        elif instruction.name in {'parameters', 'params', 'param'}:
            args = {}
            for job, parameters in instruction.args.items():
                args[job] = dict(parameters=parameters)
            deepupdate(self.current.yaml, args)
            self.current.yaml_date = instruction.date

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
            if not match(job.name, Job.jobs_filter):
                logger.debug("Skipping %s. Filtered.", job)
                continue
            job.repository = self.current.head.repository
            jobs[job.name] = job

        return jobs

    @asyncio.coroutine
    def run(self):
        head = self.current.head

        try:
            jenkins_yml = yield from GITHUB.fetch_file_contents(
                head.repository, 'jenkins.yml', ref=head.fullref,
            )
            logger.info("Loading jenkins.yml.")
        except ApiNotFoundError:
            logger.warn("No jenkins.yml. Skipping.")
            raise SkipHead()

        try:
            self.current.job_specs = self.list_job_specs(jenkins_yml)
        except Exception as e:
            logger.warn("Failed to list jobs: %s", e)
            self.current.errors.append(Error(
                "Failed to load `jenkins.yml`:\n\n```\n%s\n```" % (e,),
                self.current.last_commit.date
            ))
            return

        self.current.all_job_specs = self.current.job_specs
        self.current.jobs = head.repository.jobs

        for name, args in self.current.yaml.items():
            if name not in self.current.job_specs:
                self.current.errors.append(Error(
                    body="Can't override unknown job %s." % (name,),
                    date=self.current.yaml_date,
                ))
                continue

            current_spec = self.current.job_specs[name]
            config = dict(deepcopy(current_spec.config), **args)
            overlay_spec = JobSpec(name, config)
            logger.info("Ephemeral update of %s spec.", name)
            self.current.job_specs[name] = overlay_spec
