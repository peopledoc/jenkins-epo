import dbm
import fcntl
import logging
import os
import shelve
import time

from .settings import SETTINGS


logger = logging.getLogger(__name__)


class Cache(object):
    def get(self, key):
        try:
            _, value = self.storage[key]
            logger.debug("Hit %s", key)
            return value
        except KeyError:
            logger.debug("Miss %s", key)
            raise
        except Exception:
            # Looks like this key is corrupted.
            logger.debug("Drop corrupted key %r", key)
            del self.storage[key]
            raise KeyError(key)

    def set(self, key, value):
        self.storage[key] = (time.time(), value)
        return self.storage[key]

    def purge(self):
        # Each data is assigned a last-seen-valid date. So if this date is old,
        # this mean we didn't check the validity of the data.  We consider a
        # repository take less 60s to process. If the last-seen hasn't been
        # updated, this mean that the query wont happen anymore (PR is closed,
        # etc.)
        repo_count = len(SETTINGS.REPOSITORIES.split())
        rounds_delta = (
            2 * (SETTINGS.LOOP or 20) +
            SETTINGS.CACHE_LIFE * repo_count
        )
        limit = time.time() - rounds_delta
        cleaned = 0
        for key in list(self.storage.keys()):
            try:
                last_seen_date, _ = self.storage[key]
            except Exception:
                pass
            else:
                if last_seen_date > limit:
                    continue

            del self.storage[key]
            cleaned += 1

        if cleaned:
            logger.debug("Clean %s key(s)", cleaned)


class MemoryCache(Cache):
    def __init__(self):
        self.storage = {}


class FileCache(Cache):
    def __init__(self):
        self.open()

    def open(self):
        self.lock = open(SETTINGS.CACHE_PATH + '.lock', 'ab')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            mode = 'c'
        except IOError:
            logger.warn("Cache locked, using read-only")
            mode = 'r'
            self.lock.close()
            self.lock = None

        try:
            self.storage = shelve.open(SETTINGS.CACHE_PATH, mode)
        except Exception as e:
            if mode != 'c':
                raise
            logger.warn("Dropping corrupted cache on %s", e)
            self.lock.truncate(0)
            self.storage = shelve.open(SETTINGS.CACHE_PATH, mode)

    def close(self):
        self.save()
        self.storage.close()
        if self.lock:
            fcntl.lockf(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            os.unlink(self.lock.name)

    def destroy(self):
        self.close()
        os.unlink(SETTINGS.CACHE_PATH + '.db')

    def save(self):
        self.storage.sync()
        logger.debug("Saved %s.", SETTINGS.CACHE_PATH)

    def set(self, key, value):
        if not self.lock:
            return time.time(), value

        try:
            return super(FileCache, self).set(key, value)
        except dbm.error:
            logger.exception("Failed to save to cache, flushing cache")
            self.destroy()
            self.open()
            return super(FileCache, self).set(key, value)
        except Exception:
            logger.exception("Failed to save to cache.")
            return time.time(), value

    def purge(self):
        if not self.lock:
            return

        super(FileCache, self).purge()
        self.storage.sync()

    def __del__(self):
        self.close()


CACHE = FileCache()
