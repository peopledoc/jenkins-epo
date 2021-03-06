from datetime import timedelta
from unittest.mock import patch, MagicMock

from libfaketime import fake_time
import pytest


def test_purge(SETTINGS):
    SETTINGS.CACHE_LIFE = 10
    SETTINGS.REPOSITORIES = 'owner/repository1 owner/repository2'

    from jenkins_epo.cache import MemoryCache

    cache = MemoryCache()
    with fake_time('2012-12-21 00:00:00 UTC') as time:
        cache.set('key', 'data')
        cache.purge()
        data = cache.get('key')
        assert 'data' == data

        time.tick(timedelta(seconds=1800))
        cache.purge()
        with pytest.raises(KeyError):
            cache.get('key')


@patch('jenkins_epo.cache.fcntl')
@patch('jenkins_epo.cache.shelve.open')
def test_corruptions(dbopen, fcntl):
    from jenkins_epo.cache import FileCache

    dbopen.side_effect = [Exception(), MagicMock()]
    my = FileCache()
    my.open()

    with pytest.raises(KeyError):
        my.storage.__getitem__.side_effect = Exception()
        my.get('key')

    my.storage.keys.return_value = ['key']
    my.purge()


@patch('jenkins_epo.cache.fcntl')
@patch('jenkins_epo.cache.shelve.open')
def test_close(dbopen, fcntl):
    from jenkins_epo.cache import FileCache

    my = FileCache()
    my.close()
    assert my.storage.sync.mock_calls


@patch('jenkins_epo.cache.os.unlink')
@patch('jenkins_epo.cache.FileCache.close')
def test_destroy(close, unlink):
    from jenkins_epo.cache import FileCache

    my = FileCache()
    my.destroy()

    assert unlink.mock_calls
    assert close.mock_calls
