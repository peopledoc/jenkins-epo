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

import asyncio
import logging

from aiohttp import web

from .workers import WORKERS
from .procedures import process_url
from .tasks import ProcessUrlTask

app = web.Application()
logger = logging.getLogger(__name__)


@asyncio.coroutine
def simple_webhook(request):
    logger.info("Processing simple webhook event.")
    url = request.GET['head']
    priority = ('10-webhook', url)
    yield from WORKERS.enqueue(
        ProcessUrlTask(priority, url, callable_=process_url)
    )
    return web.json_response({'message': 'Event processing in progress.'})


app.router.add_post('/simple-webhook', simple_webhook, name='simple-webhook')
