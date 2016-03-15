from datetime import timedelta
from unittest.mock import patch, MagicMock

from freezegun import freeze_time


@patch('jenkins_ghp.cache.SETTINGS')
def test_purge(SETTINGS):
    SETTINGS.GHP_LOOP = 10

    from jenkins_ghp.cache import MemoryCache

    cache = MemoryCache()
    with freeze_time('2012-12-21 00:00:00 UTC') as time:
        cache.set('key', 'data')
        cache.purge()
        date, data = cache.get('key')
        assert 'data' == data

        time.tick(timedelta(seconds=21))
        cache.purge()
        try:
            cache.get('key')
            assert False, "Key not purged"
        except KeyError:
            pass
