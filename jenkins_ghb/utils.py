import bdb
import fnmatch
import functools
import logging

from retrying import retry


logger = logging.getLogger(__name__)


unfiltered_exceptions = {
    bdb.BdbQuit,
    KeyboardInterrupt,
    NameError,
    TypeError,
}


def retry_blacklist(exception):
    if isinstance(exception, tuple(unfiltered_exceptions)):
        return False

    logger.warn(
        "Retrying on %r: %s",
        type(exception).__name__,
        str(exception) or repr(exception)
    )
    return True


retry = functools.partial(
    retry,
    retry_on_exception=retry_blacklist,
    wait_exponential_multiplier=500,
    wait_exponential_max=10000,
)


def match(item, patterns):
    return not patterns or [p for p in patterns if fnmatch.fnmatch(item, p)]
