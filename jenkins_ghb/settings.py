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
    # Drop into Pdb on unhandled exception
    'GHIB_DEBUG': False,
    # Do not trigger jobs nor touch GitHub statuses.
    'GHIB_DRY_RUN': False,
    'GHIB_IGNORE_STATUSES': '',
    'GHIB_LIMIT_JOBS': '',
    'GHIB_LIMIT_PR': '',
    # Trigger loop
    'GHIB_LOOP': 0,
    # When commenting on PR
    'GHIB_NAME': 'Jenkins GitHub Builder',
    'GHIB_VERBOSE': '',
    'GITHUB_TOKEN': None,
    'JENKINS_URL': 'http://localhost:8080',
})
