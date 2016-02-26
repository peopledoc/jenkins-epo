Is your Jenkins crazy?

| |crazy|

####################################
 Jenkins independant GitHub Builder
####################################

| |CI|

A pure python poller based on GitHub API. This is an alternative solution to
jenkins poll or GitHub webhook.


Features
========

- Query GitHub API to poll PR instead of cloning repository.
- Query Jenkins API without jar nor JRE.
- Set commit status as soon as job is in the queue.
- Skip jobs in PR comments.
- Rebuild jobs on demand or on failure.
- Requeue jobs on queue loss.
- Retry on network failure.
- Nice with humans: wait for queue to be empty before queuing new PR jobs.
- Update GitHub status according to Jenkins builds.


Skipping jobs
-------------

If some jobs are unrelated to your PR, you can skip them with a YAML comment:

.. code-block:: markdown

   ```
   jenkins:
      skip: [app-doc, app-assets, '(?!.*notskipped.*)']
   ```

Installation
============

::

   pip3 install jenkins-ghb
   # Check with one PR and one JOB
   GITHUB_TOKEN=XXX GHIB_LIMIT_PR=*/7823 GHIB_LIMIT_JOBS=app-doc jenkins-ghb list-pr
   # Run one iteration to check
   GITHUB_TOKEN=XXX GHIB_LIMIT_PR=*/7823 GHIB_LIMIT_JOBS=app-doc jenkins-ghb bot

   # Make it a service
   editor /etc/jenkins-ghb.conf
   systemctl daemon-reload
   systemctl status jenkins-ghb


.. |CI| image:: https://circleci.com/gh/novafloss/jenkins-github-builder.svg?style=shield
   :target: https://circleci.com/gh/novafloss/jenkins-github-builder
   :alt: CI Status

.. |crazy| image:: crazy-cat.gif
   :alt: Crazy cat
