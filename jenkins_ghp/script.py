import os
import logging


logger = logging.getLogger(__name__)


def entrypoint():
    debug = os.environ.get('GHP_VERBOSE') or os.environ.get('GHP_DEBUG')
    if debug:
        format = '[%(name)-24s %(levelname)8s] %(message)s'
        level = logging.DEBUG
    else:
        format = '[%(levelname)-8s] %(message)s'
        level = logging.INFO

    logging.basicConfig(level=logging.WARNING, format=format)
    logging.getLogger('jenkins_ghp').setLevel(level)

    logger.info("Starting jenkins-ghp")
    logger.debug("Debug mode enabled")

    # Import modules after logging is setup
    from .main import main

    try:
        main()
    except KeyboardInterrupt:
        logger.info("Done")


if __name__ == '__main__':
    entrypoint()
