############
 Installing
############

Jenkins EPO is a Python3.4+ software configured by environment variables. The
package ships a systemd unit reading environment variable from
``/etc/jenkins-epo.conf`` file.

The recommended way of deploying Jenkins EPO is through Ansible with
`bersace.jenkins-epo <https://galaxy.ansible.com/bersace/jenkins-epo/>`_.

But the first requirement is a Jenkins up and running. ``jenkins-epo
list-plugins`` lists required Jenkins plugins to run managed jobs. It's up to
Jenkins administrator to install these plugins.

Jenkins must be able to clone repositories with HTTPS. Register a Jenkins
credentials for HTTPS clone, and set ``JOBS_CREDENTIALS`` according to it.

Next step is to have a GitHub API token. You can create one associated with the
GitHub user assigned to Jenkins to clone.

Test your settings like this::

    GITHUB_TOKEN=XXX JENKINS_URL=http://jenkins.lan JOBS_CREDENTIALS=github-https jenkins-epo process https://github.com/owner/repo1/tree/master

Then write it to Ansible vars or in ``/etc/jenkins-epo.conf`` like this:

.. literalinclude:: ../jenkins-epo.conf

And reload with ``systemctl restart jenkins-epo``. Watch it with
``journalctl -fu jenkins-epo`` !


Setting up WebHook
==================

To increase EPO reactivity, you can use webhooks. EPO listen for webhook on
port 2819. There is two webhooks entrypoints.


``/simple-webhook``
-------------------

Just pass head URL as ``head`` GET param::

  curl -X POST http://localhost:2819/simple-webhook?head=https://github.com/owner/repo1/tree/master

At the end of each build, ``jenkins-yml-runner`` can notify one URL. EPO tells
Jenkins which URL to notify using ``SERVER_URL``. ``SERVER_URL`` points to EPO
public address, accessible from node executing the build::

  HOST=0.0.0.0 PORT=2819 SERVER_URL=http://jenkins.lan:2819 jenkins-epo bot

Watch for the following message at the end of your build log::

  + jenkins-yml-runner notify
  Notifying http://jenkins.lan:2819/simple-webhook?head=https://github.com/owner/repo1/tree/master (POST).
  Success: b'{"message": "Event processing in progress."}'.
  POST BUILD TASK : SUCCESS

Nice! Persist ``SERVER_URL`` in ``/etc/jenkins-epo.conf`` and you're done. EPO
and Jenkins communicate to speed up the pipeline! Now you can go further!


``/github-webhook``
-------------------

If you can open a port to the world, you can tell GitHub to notify EPO of
changes on your protected branches or PR. Here is basically how to setup an
nginx proxy to serve EPO to GitHub.

#. Register the domain, get the certificate, a host, etc.
#. Configure nginx, here is a sample host configuration.

   .. literalinclude:: nginx-relay.conf
#. Test it! ::

     curl -X POST -H 'X-Forwarded-For: 8.8.8.8' https://jenkins.company.com/github-webhook
     curl -X POST -H 'X-Forwarded-For: 192.30.252.25' https://jenkins.company.com/github-webhook

#. Now register EPO in GitHub.

   You need an admin ``GITHUB_TOKEN``. *You should use a separate admin token*.
   For example, use a personnal token of yours.

   To increase security, EPO shares a secret with GitHub to sign payload. Save
   it in ``/etc/jenkins-epo.conf``.

   ::

      export GITHUB_SECRET=$(pwgen 64 1)
      SERVER_URL=https://jenkins.company.com/ GITHUB_TOKEN=XXX jenkins-epo register

   Jenkins and GitHub can ping different URLs. Just override ``SERVER_URL`` with
   GitHub URL when calling ``register``.

#. In GitHub web interface, you can test webhook delivery, ping webhook and
   redeliver a payload.


Now test it for real : push a new commit in a PR and see how fast the jobs are
triggered!


Adding a new repository
=======================

EPO can manage multiple repositories! Here are the steps to add a repository to
EPO.

#. Add your bot user to repository's collaborators *with write access*.
#. Ensure your default branch is protected if you want it to be tested!
#. Add ``owner/repo2`` to ``REPOSITORIES`` setting in ``/etc/jenkins-epo.conf``.
#. Restart EPO::

     systemctl restart jenkins-epo

#. Watch it with ``journalctl -fu jenkins-epo``, you should see::

     =a892= [INFO    ] Working on https://github.com/owner/repo2/tree/master (a892eb2).
     =a892= [WARNING ] No jenkins.yml. Skipping.
     =a892= [INFO    ] Processed https://github.com/owner/repo2/tree/master (a892eb2).

#. Register GitHub webhook for this repository::

     GITHUB_TOKEN=XXX REPOSITORIES=owner/repo2 jenkins-epo register

#. Create a PR to add ``jenkins.yml``.

Enjoy!
