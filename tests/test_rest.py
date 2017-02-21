import asyncio
from asynctest import CoroutineMock, Mock

import pytest


@pytest.mark.asyncio
@asyncio.coroutine
def test_get(mocker):
    ClientSession = mocker.patch('jenkins_epo.jenkins.aiohttp.ClientSession')
    from jenkins_epo.jenkins import RESTClient

    client = RESTClient()
    client = client('http://jenkins/path').subpath

    session = ClientSession.return_value

    response = Mock(name='response')
    session.get = CoroutineMock(return_value=response)
    response.read = CoroutineMock(
        return_value=repr(dict(unittest=True)).encode('utf-8')
    )

    payload = yield from client.aget(param=1)

    assert payload['unittest']


@pytest.mark.asyncio
@asyncio.coroutine
def test_post(mocker):
    ClientSession = mocker.patch('jenkins_epo.jenkins.aiohttp.ClientSession')
    from jenkins_epo.jenkins import RESTClient

    client = RESTClient()
    client = client('http://jenkins/path').subpath

    session = ClientSession.return_value

    response = Mock(name='response')
    session.post = CoroutineMock(return_value=response)
    response.read = CoroutineMock(
        return_value=repr(dict(unittest=True)).encode('utf-8')
    )

    payload = yield from client.apost(param=1)

    assert ': True' in payload
