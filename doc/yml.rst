=========================
 Writing ``jenkins.yml``
=========================

``jenkins.yml`` allow developers to define per project configuration of the
pipeline. The ``jenkins.yml`` file provide a mapping of all jobs to manage. The
special entry ``settings`` allow to overrides some defaults settings.


Defining a job
==============

The simplest job definition is a oneline YAML entry:

.. code-block:: yaml

   app-job: tox -r

Commands are wrapped in a ``bash`` script, executede with ``-eux`` shell
options. This mean that any failing command breaks the job, undefined variable
are not accepted and each executed command is echoed on stderr.

You can actually add a bunch of Jenkins job feature in YML:

.. code-block:: yaml

   app-job:
     # Limit job on specific branch
     branches: master
     # Attach job to one stage of the CI pipeline
     stage: test
     # Target a specific node or node label
     node: slave0
     # Matrix. Only values in YML are triggered
     axis:
       TOXENV:
       - py34
       - py35
     # job parameterer, value is always read from YML
     parameters:
       TESTS: tests/
     # The script
     script: |
       tox -re $TOXENV -- $TESTS
     # clean up script, executed even on cancel/abort.
     after_script: |
       rm -rf coverage.xml


Tests report and coverage
=========================

``jenkins.yml`` jenkins generated jobs are full featured ! Each build is runned
with a ``CI_ARTEFACTS`` env var pointing to a directory archived at the end of
the job. The job will import all ``xunit*.xml`` files to generate a test report
and feed *Cobertura* plugin with ``coverage.xml`` to generate a coverage report.

.. code-block:: yaml

   app-units: |
     pytest -vvvv --strict --showlocals \
         --junit-xml={env:CI_ARTEFACTS:log/}/xunit.xml \
         --cov=app --cov-report=xml:{env:CI_ARTEFACTS:log}/coverage.xml


Create a periodic job
=====================

You can define periodic job from ``jenkins.yml``. Theses jobs are **never**
triggered on push. Jenkins EPO take care of maintaining the job in Jenkins
according to the latest ``jenkins.yml`` version.

.. code-block:: yaml

   app-task:
     # Run this job around 3:00AM
     periodic: H 3 * * *
     # Run only on master
     default_revision: refs/heads/master
