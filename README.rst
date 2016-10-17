Time for kickass CI !

| |hulk|

#############
 Jenkins EPO
#############

| |PyPI| |CI| |CodeCov|

Implements extended CI features on top of Jenkins and GitHub for in-house CI.


Features
========

- Define jobs from repository in `jenkins.yml
  <https://github.com/novafloss/jenkins-yml>`_.
- Jobs pipeline façon GitLab CI.
- Query GitHub API to poll open PR instead of polling git repository.
- Read instructions from PR comments.
- Cancel running jobs when pushing new commits.
- Report issue on broken protected branches.
- Auto-merge PR.
- Works behind firewall.
- Extensible through entry-point.


Installation
============

On your poller host:

::

   pip3 install jenkins-epo
   # Setup env vars
   export GITHUB_TOKEN=YOUR_SECRET_TOKEN JENKINS_URL=http://myjenkins.lan
   export REPOSITORIES=owner/repo
   # Check repository is manageable
   jenkins-epo list-heads
   # Trigger a dry run
   DRY_RUN=1 jenkins-epo bot
   # Run it for real
   jenkins-epo bot

Now write a ``jenkins.yml`` file and open a PR::

   myjob: |
       tox -r


Many instructions are available. Just ask the bot by commenting ``jenkins:
help`` in an open PR!


.. |CI| image:: https://circleci.com/gh/novafloss/jenkins-epo.svg?style=shield
   :target: https://circleci.com/gh/novafloss/jenkins-epo
   :alt: CI Status

.. |CodeCov| image:: https://codecov.io/gh/novafloss/jenkins-epo/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/novafloss/jenkins-epo
   :alt: Code coverage

.. |hulk| image:: https://github.com/novafloss/jenkins-epo/raw/master/hulk.gif
   :alt: Hulk

.. |PyPI| image:: https://img.shields.io/pypi/v/jenkins-epo.svg
   :target: https://pypi.python.org/pypi/jenkins-epo
   :alt: Version on PyPI
