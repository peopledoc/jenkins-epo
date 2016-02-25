import logging
import os


logger = logging.getLogger(__name__)


class EnvironmentSettings(object):
    def __init__(self, defaults):
        for k, v in sorted(defaults.items()):
            v = os.environ.get(k, v)
            try:
                v = int(v)
            except (TypeError, ValueError):
                pass
            setattr(self, k, v)
            logger.debug("%s=%r", k, v)
        logger.debug("Environment loaded.")


SETTINGS = EnvironmentSettings(defaults={
    # Work only on this PR github full URL.
    'DEBUG_PR': None,
    # [owner/repository:job1,job2 ...]
    'GITHUB_JOBS': '',
    'GITHUB_TOKEN': None,
    'GITHUB_USERNAME': None,
    'GITHUB_PASSWORD': None,
    'JENKINS_URL': 'http://localhost:8080',
    # Drop into Pdb on unhandled exception
    'PDB': False,
    # Wait this milliseconds before actually do something.
    'WAIT_FIXED': 15000,
    # Trigger loop
    'RETRY_AFTER': 60,
    # Jenkins job param name.
    'REVISION_PARAM': 'REVISION',
})
