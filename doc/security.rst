##########
 Security
##########

CI is about executing code. Here are some note on what checks are implemented in
EPO to increase security.

- EPO considers only collaborators with *write* access.
- You can override collaborators in ``jenkins.yml`` of default branch:
  .. code-block:: yaml

     settings:
       collaborators:
         - owner
         - admin
         - dev0
         - dev1

- EPO builds only PR from collaborators.
- EPO reads instructions from collaborators only.
- You can allow an external PR to be tested. Say ``jenkins: allow`` in a
  comment. Author instructions **before ``allow`` wont be processed**. PR author
  will be considered as a collaborator with **write** access for this PR. This
  include automatic merge.
- Webhook are used only to determine the URL of the head: either
  ``https://github.com/owner/repo/tree/branch`` or
  ``https://github.com/owner/repo/pull/1234``. Comments are not parsed from
  webhook.
- GitHub webhook payload **must** be signed with `Hub secret token
  <https://developer.github.com/webhooks/securing/>`_.
- For now, GitHub is accessed using a token. But Jenkins must be open.
