# This file is part of jenkins-epo
#
# jenkins-epo is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# jenkins-epo is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# jenkins-epo.  If not, see <http://www.gnu.org/licenses/>.

import ast
import collections
import logging

import aiohttp
from yarl import URL

from .utils import retry


logger = logging.getLogger(__name__)


class Payload(object):
    @classmethod
    def factory(cls, status, headers, payload):
        if isinstance(payload, list):
            return PayloadList(status, headers, payload)
        elif isinstance(payload, dict):
            return PayloadDict(status, headers, payload)
        elif isinstance(payload, str):
            return PayloadString(status, headers, payload)
        else:
            raise Exception("Unhandled payload type")

    def __init__(self, status, headers, payload):
        super(Payload, self).__init__(payload)
        self.status = status
        self.headers = headers


class PayloadList(Payload, collections.UserList):
    pass


class PayloadDict(Payload, collections.UserDict):
    pass


class PayloadString(Payload, collections.UserString):
    pass


class Client(object):
    def __init__(self, url=''):
        self.url = url

    def __call__(self, url):
        if not url.startswith('http://'):
            url = self.url.rstrip('/') + '/' + str(url)
        return self.__class__(url)

    def __getattr__(self, name):
        return self(name)

    @retry
    def aget(self, **kw):
        session = aiohttp.ClientSession()
        url = URL(self.url)
        if kw:
            url = url.with_query(**kw)
        logger.debug("GET %s", url)
        try:
            response = yield from session.get(url, timeout=10)
            payload = yield from response.read()
        finally:
            yield from session.close()
        response.raise_for_status()
        payload = payload.decode('utf-8')
        if response.content_type == 'text/x-python':
            payload = ast.literal_eval(payload)
        return Payload.factory(response.status, response.headers, payload)

    @retry
    def apost(self, **kw):
        session = aiohttp.ClientSession()
        url = URL(self.url)
        if kw:
            url = url.with_query(**kw)
        logger.debug("POST %s", url)
        try:
            response = yield from session.post(url, timeout=10)
            payload = yield from response.read()
        finally:
            yield from session.close()
        response.raise_for_status()
        payload = payload.decode('utf-8')
        return Payload.factory(response.status, response.headers, payload)
