import os
import logging

try:
    import cPickle as pickle
except ImportError:
    import pickle


logger = logging.getLogger(__name__)


class LazyPickleCache(dict):
    def __init__(self):
        self.loaded = False
        self.cachefile = 'ghb_cache.pickle'

    def get(self, *a, **kw):
        self.load()
        return super(LazyPickleCache, self).get(*a, **kw)

    def load(self):
        if not self.loaded and os.path.exists(self.cachefile):
            with open(self.cachefile, 'rb') as fo:
                self.update(pickle.load(fo))
                logger.debug('Loaded %s', self.cachefile)
        self.loaded = True

    def reset(self):
        if os.path.exists(self.cachefile):
            os.unlink(self.cachefile)
        logger.info("Cleaned %r", self.cachefile)

    def save(self):
        with open(self.cachefile, 'w+b') as fo:
            pickle.dump(dict(self.items()), fo)
            logger.debug("Saved to %s", self.cachefile)


CACHE = LazyPickleCache()
