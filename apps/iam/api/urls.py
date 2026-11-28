"""The routes of the iam app. Each part keeps its own list, so two parts never edit one file.

Workspace members are routes of a workspace and live in ``apps/workspaces/api``.
"""

from . import members_urls, tenants_urls

urlpatterns = [*members_urls.urlpatterns, *tenants_urls.urlpatterns]
