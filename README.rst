Is your Jenkins crazy?

| |crazy|

#######################
 Jenkins GitHub Poller
#######################

| |CI|

A pure python poller based on GitHub API. This is an alternative solution to
jenkins poll or GitHub webhook.


Features
========

- Query GitHub API to poll open PR instead of cloning repository.
- Query Jenkins API without jar nor JRE.
- Set commit status as soon as job is in the queue.
- Skip jobs in PR comments.
- Rebuild jobs failed jobs on demand.
- Requeue jobs on queue loss.
- Retry on network failure.
- Nice with humans: wait for queue to be empty before queuing new PR jobs.
- Update GitHub commit status from Jenkins status.


Skipping jobs
-------------

If some jobs are unrelated to your PR, you can skip them with a YAML comment:

.. code-block:: markdown

   ```
   jenkins:
      skip: [app-doc, app-assets, '(?!.*notskipped.*)']
   ```

Other instructions are available. Just ask the bot by commenting ``jenkins:
help`` in an open PR!


Installation
============

::

   pip3 install -e git+https://github.com/novafloss/jenkins-github-poller.git#egg=jenkins-ghp
   # Check with one PR and one JOB
   export GITHUB_TOKEN=XXX GHP_LIMIT_PR=*/7823 GHP_LIMIT_JOBS=app-doc
   jenkins-ghp list-pr
   # Trigger a dry run
   GHP_DRY_RUN=1 jenkins-ghp bot

   # Make it a service
   editor /etc/jenkins-ghp.conf
   systemctl daemon-reload
   systemctl status jenkins-ghp


.. |CI| image:: https://circleci.com/gh/novafloss/jenkins-github-poller.svg?style=shield
   :target: https://circleci.com/gh/novafloss/jenkins-github-poller
   :alt: CI Status

.. |crazy| image:: crazy-cat.gif
   :alt: Crazy cat
