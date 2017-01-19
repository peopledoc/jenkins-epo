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

The bot's story
===============

The bot executes the extensions listed in setup.py's entry point
'jenkins_epo.bot.extensions'. Each entry point defines a stage number which is
used by the bot to decide in which order to execute extensions. The
``jenkins-epo list-extensions`` command outputs the pipeline.

The ``bot.run()`` asyncio coroutine invoked by the ``jenkins-epo bot`` command
creates a payload in ``self.current`` available in each extension's method
call. Note that the ``LOOP=1`` environment variable will make the ``jenkins-epo
bot`` command to loop forever over calls of ``bot.run()``.

First step of ``bot.run()`` is calling the ``ext.begin()`` method of each
extension. This method should encapsulate any of the extension's variable
initialization.

Then, ``bot.run()`` executes the ``ext.process_instruction(instruction)``
extension method for each instruction parsed from the github comments by the
bot. You'll note from examples such as the OPM extension that the bot gives
instructions to itself in HTML comments when posting user feedback. This
demonstrates how to maintain a state for an extension on a pull request.

Finnaly, the ``ext.run()`` extension coroutine is called for each extension.
This is where the extension is executed and works with the different APIs.

A special ``SkipHead`` exception may be raised by the extension's ``ext.begin()``
or ``ext.run()`` methods which will cause ``bot.run()`` to return None,
aborting the current pipeline for the current context.

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
