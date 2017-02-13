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
import hmac
import hashlib
import logging

from aiohttp import web

from .procedures import process_url
from .repository import REPOSITORIES, Repository, WebHook
from .settings import SETTINGS
from .tasks import ProcessUrlTask
from .workers import WORKERS, Task

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


def compute_signature(payload, secret):
    return "sha1=%s" % (
        hmac.new(key=secret, msg=payload, digestmod=hashlib.sha1)
        .hexdigest()
    )


@asyncio.coroutine
def github_webhook(request):
    logger.info("Processing GitHub webhook event.")
    github_signature = request.headers['X-Hub-Signature']
    payload = yield from request.read()
    yield from request.release()
    key = SETTINGS.GITHUB_SECRET.encode('ascii')
    my_signature = compute_signature(payload, key)
    if github_signature != my_signature:
        return web.json_response({'message': 'Invalid signature.'}, status=403)
    return web.json_response({'message': 'Event processing in progress.'})


app.router.add_post('/github-webhook', github_webhook, name='github-webhook')


@asyncio.coroutine
def register_webhook():
    for qualname in REPOSITORIES:
        yield from WORKERS.enqueue(RegisterTask(qualname))
    yield from WORKERS.queue.join()


class RegisterTask(Task):
    def __init__(self, qualname):
        super(RegisterTask, self).__init__()
        self.qualname = qualname

    @asyncio.coroutine
    def __call__(self):
        webhook_url = fullurl(route='github-webhook')
        webhook = WebHook({
            "name": "web",
            "active": True,
            "events": [
                "commit_comment",
                "issue_comment",
                "pull_request",
                "push",
            ],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "insecure_ssl": "0",
                "secret": SETTINGS.GITHUB_SECRET,
            }
        })

        owner, name = self.qualname.split('/')
        repository = yield from Repository.from_name(owner, name)
        payload = yield from repository.fetch_hooks()
        hooks = repository.process_hooks(payload, webhook_url)
        hookid = None
        for hook in hooks:
            if hook == webhook:
                logger.info("Webhook for %s uptodate.", repository)
                return
            else:
                hookid = hook['id']
                break
        repository.set_hook(webhook, hookid=hookid)


def fullurl(route='simple-webhook', **query):
    return (
        SETTINGS.SERVER_URL.rstrip('/') +
        str(app.router[route].url_for().with_query(query))
    )
