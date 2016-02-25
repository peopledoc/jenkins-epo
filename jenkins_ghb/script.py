import os
import logging


logger = logging.getLogger(__name__)


def entrypoint():
    debug = os.environ.get('GHIB_VERBOSE') or os.environ.get('GHIB_DEBUG')
    if debug:
        format = '[%(name)-24s %(levelname)8s] %(message)s'
        level = logging.DEBUG
    else:
        format = '%(asctime)s %(levelname)8s %(message)s'
        level = logging.INFO

    logging.basicConfig(level=logging.WARNING, format=format)
    logging.getLogger('jenkins_ghb').setLevel(level)

    logger.info("Starting jenkins-ghb")
    logger.debug("Debug mode enabled")

    # Import GHB modules after logging is setup
    from .main import main

    try:
        main()
    except KeyboardInterrupt:
        logger.info("Done")


if __name__ == '__main__':
    entrypoint()
