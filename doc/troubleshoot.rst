#################
 Troubleshooting
#################

Developers are impatient customers, but love to dive into problems to solve
them. Here are some hint when you are not satisfied by EPO. The big question is:

**My PR is not built :(( !!**

#. **EPO is a poller**

   And thus, can't react immediatly. Wait a minute or two, depending on the load
   of your Jenkins.
#. **Is your latest commit older than 4 weeks ?**

   By default, EPO discard older branch::

     =9c6e= Skipping head older than 5 weeks.

   Just rebase and you're done.
#. **Does EPO have Write access to the repository?**

   If you find the following message, consider adding write access to your
   GitHub bot user.

   ::

      =d0d0= [ERROR   ] Write access denied to owner/name.
#. **Does EPO have too many repositories to poll ?**

   GitHub limits API calls to 5000 per hour per account. EPO output warnings
   when hitting rate limit::

     =othr= [INFO    ] 92 remaining API calls. Consumed at 2017-02-07 13:50:32+00:00. Reset at 2017-02-07 14:17:43+00:00.
     =othr= [WARNING ] Throttling GitHub API calls by 121s.

   If this is the case, consider splitting EPO in two instances, with a
   different GitHub account. Dispatch repositories amongst EPO instances.

   You can also disable ``autocancel`` to reduce rate limit consumption. This
   extensions poll previous commits status to find a running build.
#. **Does EPO cache works properly ?**

   EPO cache is a file, and only one process can write to it. EPO still works if
   the cache is locked, but the cache may be outdated. ::

     =main= [WARNING ] Cache locked, using read-only

   Ensure the cache file is unlocked or your EPO instance has it's own cache
   file using ``EPO_CACHE_PATH`` env var.


Reading EPO logs
================

EPO tries to provide meaningful log messages and level. When running in systemd
unit, EPO output level as syslog token. Otherwise, log level is shown as usual::

    $ jenkins-epo list-extensions
    =main= [INFO    ] Starting jenkins-epo 1.123.
    00 outdated
    00 security
    02 yaml
    05 jenkins-createjobs
    10 jenkins-stages
    30 autocancel
    30 jenkins-autocancel
    30 skip
    49 jenkins-canceller
    50 jenkins-builder
    90 help
    90 merger
    90 report
    99 error
    =othr= [INFO    ] Done.

The first field, wrapped in ``=`` is an asyncio task identifier.

``main``
  Emitted from synchronous code, out of an async task.

``othr``
  Emitted from an unnamed task.

``wkXX``
  Emitted from a main worker task.

**Commit sha**
  Emitted from the task processing a head. This is the git sha of the current
  commit processed.
