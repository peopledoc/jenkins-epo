import os

from jenkinsapi.jenkins import Jenkins


class LazyJenkins(object):
    def __init__(self):
        self._instance = None

    def load(self):
        if not self._instance:
            url = os.environ.get('JENKINS_URL', 'http://localhost:8080')
            self._instance = Jenkins(url)

    def __getattr__(self, name):
        self.load()
        return getattr(self._instance, name)


JENKINS = LazyJenkins()
