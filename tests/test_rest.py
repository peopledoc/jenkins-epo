import asyncio

from asynctest import CoroutineMock, Mock
import pytest


def test_repr():
    from jenkins_epo.rest import Client

    client = Client()
    client = client('https://fqdn.tld/path').subpath

    assert '/path/subpath' in repr(client)


@pytest.mark.asyncio
@asyncio.coroutine
def test_get(mocker):
    ClientSession = mocker.patch('jenkins_epo.rest.aiohttp.ClientSession')
    from jenkins_epo.rest import Client

    client = Client()
    client = client('http://jenkins/path').subpath

    session = ClientSession.return_value

    response = Mock(name='response')
    response.content_type = 'text/x-python'
    session.get = CoroutineMock(return_value=response)
    response.read = CoroutineMock(
        return_value=repr(dict(unittest=True)).encode('utf-8')
    )

    payload = yield from client.aget(param=1)

    assert payload['unittest']


@pytest.mark.asyncio
@asyncio.coroutine
def test_post(mocker):
    ClientSession = mocker.patch('jenkins_epo.rest.aiohttp.ClientSession')
    from jenkins_epo.rest import Client

    client = Client()
    client = client('http://jenkins/path').subpath

    session = ClientSession.return_value

    response = Mock(name='response')
    session.post = CoroutineMock(return_value=response)
    response.read = CoroutineMock(
        return_value=repr(dict(unittest=True)).encode('utf-8')
    )

    payload = yield from client.apost(param=1)

    assert ': True' in payload


def test_payload():
    from jenkins_epo.rest import Payload

    Payload.factory(Mock(), Mock(), 'string')
    Payload.factory(Mock(), Mock(), list())
    Payload.factory(Mock(), Mock(), dict())

    with pytest.raises(Exception):
        Payload.factory(Mock(), Mock(), object())
