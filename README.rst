Is your Jenkins crazy?

.. image:: crazy-cat.gif
   :alt: Crazy cat

####################################
 Jenkins independant Github Builder
####################################

A pure python poller based on github API. This is an alternative solution to
jenkins poll or github webhook


Installation
============

::

   pip3 install jenkins-ghb
   editor /etc/jenkins-ghb.conf
   systemctl daemon-reload
   systemctl status jenkins-ghb
