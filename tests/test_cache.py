from datetime import timedelta
from unittest.mock import patch, MagicMock

from freezegun import freeze_time
import pytest


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


@patch('jenkins_ghp.cache.fcntl')
@patch('jenkins_ghp.cache.shelve.open')
def test_corruptions(dbopen, fcntl):
    from jenkins_ghp.cache import FileCache

    dbopen.side_effect = [Exception(), MagicMock()]
    my = FileCache()

    with pytest.raises(KeyError):
        my.storage.__getitem__.side_effect = Exception()
        my.get('key')

    my.storage.keys.return_value = ['key']
    my.purge()
