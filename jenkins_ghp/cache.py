import logging
import shelve
import time

from .settings import SETTINGS


logger = logging.getLogger(__name__)


class Cache(object):
    def get(self, key):
        try:
            value = self.storage[key]
            logger.debug("Hit %s", key)
            return value
        except KeyError:
            logger.debug("Miss %s", key)
            raise

    def set(self, key, value):
        self.storage[key] = (time.time(), value)
        return self.storage[key]

    def purge(self):
        # Each data is assigned a last-seen-valid date. So if this date is old,
        # this mean we didn't check the validity of the data. For example, the
        # PR has been closed or a HEAD of the branch has been updated. So we
        # can safely drop all data not validated for two rounds.
        rounds_delta = 2 * SETTINGS.GHP_LOOP or 2000
        limit = time.time() - rounds_delta
        for key in list(self.storage.keys()):
            last_seen_date, _ = self.storage[key]
            if last_seen_date > limit:
                continue

            logger.debug("Clean %s", key)
            self.storage.pop(key)


class MemoryCache(Cache):
    def __init__(self):
        self.storage = {}


class FileCache(Cache):
    CACHE_PATH = SETTINGS.GHP_CACHE_PATH

    def __init__(self):
        self.storage = shelve.open(self.CACHE_PATH, 'c')

    def purge(self):
        super(FileCache, self).purge()
        self.storage.sync()

    def __del__(self):
        self.storage.close()
        logger.debug("Saved %s", self.CACHE_PATH)


CACHE = FileCache()
