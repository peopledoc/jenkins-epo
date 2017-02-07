##########################
 Interacting with the bot
##########################

Jenkins EPO reads instructions from comments on PR, including description, and
comments on commit for protected branches.

An instruction is always prefixed with ``jenkins:``. It must be a valid YAML
dict. Instructions on multiple line must be wrapped in MarkDown code block.

Available instructions can be reported by invoking ``jenkins: man`` in an open
pull request.


Example of instructions
=======================

Simple one line instruction:

.. code-block:: yaml

   jenkins: skip


Parameterized intruction:

.. code-block:: md

   ```
   jenkins:
     jobs: '*units'
   ```


Complex instruction:

.. code-block:: md

   ``` yaml
   jenkins:
     parameters:
       test-job:
         PARAM0: 'override'
   ```


Marking urgent pull requests
============================

Jenkins EPO priorize protected branches over pull-requests. It is possible to
mark a pull request as urgent, to test it before protected branches and other
pull requests.

Add ``jenkins: urgent``, on a single line, in PR description.

.. code-block:: yaml

   jenkins: urgent
