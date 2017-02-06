#################
 The bot's story
#################


The bot is a pipeline of extensions registered from
``jenkins_epo.bot.extensions`` entry-point. Each extension has a ``stage``
property to define its position in the pipeline. Use ``jenkins-epo
list-extensions`` to see the pipeline, in processing order. The ``EXTENSIONS``
settings allow to disable some extensions.

Jenkins EPO invoke ``bot.run()`` coroutine to process one Head. The bot creates
a context in ``self.current`` available in each extension's method call.

The pipeline is a Final State Machine. The steps ``begin`` and
``process_instruction`` inspect the Head to define the state of the Head. Then
the final ``run`` step will apply next action.

First step of ``bot.run()`` is calling the ``ext.begin()`` method of each
extension. This method should encapsulate any of the extension's variable
initialization.

Then, ``bot.run()`` executes the ``ext.process_instruction(instruction)`` method
for each instruction parsed from the GitHub comments by the bot. An extension
can comment a PR and even write instruction for itself, usualy in HTML comment.
See the ``MergerExtension`` for an example. This demonstrates how to maintain a
state for an extension on a pull request.

Finnaly, the ``ext.run()`` coroutine is yielded. This is where the extension
works with the different APIs to apply the next actions on the Head : trigger
job, cancel job, report status, merge branch, etc.

``ext.begin()`` and ``ext.run()`` can abort the pipeline by raising a special
``SkipHead`` exception.
