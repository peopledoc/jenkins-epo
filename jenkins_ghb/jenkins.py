import fnmatch
import logging
from xml.etree import ElementTree as ET

from jenkinsapi.jenkins import Jenkins

from .project import Project
from .settings import SETTINGS
from .utils import retry


logger = logging.getLogger(__name__)


class LazyJenkins(object):
    limit_jobs = [p for p in SETTINGS.GHIB_LIMIT_JOBS.split(',') if p]

    def __init__(self):
        self._instance = None

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)

    @retry()
    def load(self):
        if not self._instance:
            logger.info("Connecting to Jenkins %s", SETTINGS.JENKINS_URL)
            self._instance = Jenkins(SETTINGS.JENKINS_URL)

    def list_projects(self):
        """List github projects tested on this jenkins.

        Mine jobs configs to find github remote URL. Attach each job to the
        corresponding project.

        """

        projects = {}

        for name, job in self.get_jobs():
            if self.limit_jobs:
                for pattern in self.limit_jobs:
                    if fnmatch.fnmatch(name, pattern):
                        break
                else:
                    logger.debug("Skipping %s", name)
                    continue

            config = ET.fromstring(job.get_config())
            remote_xpath_query = './/hudson.plugins.git.UserRemoteConfig/url'
            for remote_e in config.findall(remote_xpath_query):
                remote_url = remote_e.findtext('.')
                try:
                    project = Project.from_remote(remote_url)
                except ValueError:
                    logger.debug("%r is not github. Skipping.", remote_url)
                    continue

                logger.info("Managing %s", name)
                project = projects.setdefault(remote_url, project)
                project.jobs.append(job)

        return sorted(projects.values(), key=str)


JENKINS = LazyJenkins()
