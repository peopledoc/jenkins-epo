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
