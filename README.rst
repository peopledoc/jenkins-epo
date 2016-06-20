Is your Jenkins crazy?

| |crazy|

#######################
 Jenkins GitHub Poller
#######################

| |PyPI| |CI| |Code Climate| |Requires.io|

A pure python poller based on GitHub API. This is an alternative to jenkins
poll or GitHub webhook.


Features
========

- Query GitHub API to poll open PR instead of cloning repository.
- Query Jenkins API without jar nor JRE.
- Set commit status as soon as job is in the queue.
- Skip jobs from PR comments.
- Rebuild failed jobs from PR comments.
- Requeue jobs on queue loss.
- Requeue aborted jobs.
- Retry on network failure.
- Nice with humans: queue new jobs only on empty Jenkins queue.
- Update GitHub commit status from Jenkins status.
- Report issue on broken protected branch.
- Creates jobs from `jenkins.yml <https://github.com/novafloss/jenkins-yml>`_.


Skipping jobs
-------------

If some jobs are unrelated to your PR, you can skip them with a YAML comment:

::

   ```
   jenkins:
      skip: [app-doc, app-assets, '(?!.*notskipped.*)']
   ```

Other instructions are available. Just ask the bot by commenting ``jenkins:
help`` in an open PR!


Installation
============

In your Jenkins, for each job :

- Tick *Build when a change is pushed on GitHub*.
- **Untick** *SCM polling*. jenkins-ghp actually replaces this feature.


On poller host:

::

   pip3 install jenkins-ghp
   # Check jobs managed
   export GITHUB_TOKEN=YOUR_SECRET_TOKEN JENKINS_URL=http://myjenkins.lan
   jenkins-ghp list-jobs
   # Trigger a dry run
   GHP_DRY_RUN=1 jenkins-ghp bot

   # Make it a service
   editor /etc/jenkins-ghp.conf
   systemctl daemon-reload
   systemctl status jenkins-ghp


Development
===========

- For testing, use ``tox``.
- For releasing, use ``tox -e release fullrelease``.


.. |CI| image:: https://circleci.com/gh/novafloss/jenkins-github-poller.svg?style=shield
   :target: https://circleci.com/gh/novafloss/jenkins-github-poller
   :alt: CI Status

.. |Code Climate| image:: https://img.shields.io/codeclimate/github/novafloss/jenkins-github-poller.svg
   :target: https://codeclimate.com/github/novafloss/jenkins-github-poller
   :alt: Code climate

.. |crazy| image:: https://github.com/novafloss/jenkins-github-poller/raw/master/crazy-cat.gif
   :alt: Crazy cat

.. |PyPI| image:: https://img.shields.io/pypi/v/jenkins-ghp.svg
   :target: https://pypi.python.org/pypi/jenkins-ghp
   :alt: Version on PyPI

.. |Requires.io| image:: https://img.shields.io/requires/github/novafloss/jenkins-github-poller.svg
   :target: https://requires.io/github/novafloss/jenkins-github-poller/requirements/
   :alt: Requirements status
