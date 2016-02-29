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
    'GHP_DEBUG': False,
    # Do not trigger jobs nor touch GitHub statuses.
    'GHP_DRY_RUN': False,
    'GHP_IGNORE_STATUSES': '',
    'GHP_LIMIT_JOBS': '',
    'GHP_LIMIT_PR': '',
    # Trigger loop
    'GHP_LOOP': 0,
    # When commenting on PR
    'GHP_NAME': 'Jenkins GitHub Builder',
    'GHP_VERBOSE': '',
    'GITHUB_TOKEN': None,
    'JENKINS_URL': 'http://localhost:8080',
})
