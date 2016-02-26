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
    # Drop into Pdb on unhandled exception
    'GHIB_DEBUG': False,
    'GHIB_IGNORE_STATUSES': '',
    'GHIB_LIMIT_JOBS': '',
    'GHIB_LIMIT_PR': '',
    # Trigger loop
    'GHIB_LOOP': 0,
    # When commenting on PR
    'GHIB_NAME': 'Jenkins GitHub Builder',
    'GHIB_VERBOSE': '',
    # [owner/repository:job1,job2 ...]
    'GITHUB_JOBS': '',
    'GITHUB_TOKEN': None,
    'GITHUB_USERNAME': None,
    'GITHUB_PASSWORD': None,
    'JENKINS_URL': 'http://localhost:8080',
    # Wait this milliseconds before actually do something.
    'WAIT_FIXED': 15000,
    # Jenkins job param name.
    'REVISION_PARAM': 'REVISION',
})
