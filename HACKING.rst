#########
 Hacking
#########


Releasing
=========

Jenkins EPO version number is read from latest Git tag with ``git describe
--tags``. Use the following listing to tag and upload a new release.

.. code-block:: console

   $ ./release 1.90

Release early, release often is the way of Jenkins EPO !


Ideas of improvements
=====================

Feel free to contribute :)

- Limit les webhooks to managed repositories.
- Manage regular Jenkins notifications
  (https://wiki.jenkins-ci.org/display/JENKINS/Notification+Plugin).
- Aggregate error comment.
- Comment *still broken* on previous *master is broken* rather than opening a
  new issue.
- Put *Backed* ASAP, just after stage extension.
- Manage GitHub webhook event.
- Test GraphQL.
- Add ``clean-job`` command to drop jobs undefined un protected branches.
- Comment old PR with «push a new commit».
- Switch to full AsyncIO
  - drop cached_request
  - drop jenkinsapi
  - drop githubpy
  - see siesta
- Test merge commit (pull/XXXX/{head,merge})
- json log (EPO_JSON=path/to/log.json), to debug asynchronicity
- metrics: build count, total time on Jenkins, cancelled build (how much time
  saved), etc.
- Pipeline dashboard
- Command ``install-plugins``. Install plugins on Jenkins
- Command ``settings [repo]`` dump settings, jenkins.yml loaded.
- Keep build forever on Jenkins for build reported in *master is broken*
- i18n: translate documentation, comments, logs
- Add ansicolor to Jenkins job ?
- Distinct global/per project settings.
- Disable extensions from jenkins.yml.
- Support "jenkins, skip", "Jenkins, rebuild.", "@bot merge", "jenkins:rebuild"
- Lint instructions : refuse ``jenkins: urgent`` out of description.
