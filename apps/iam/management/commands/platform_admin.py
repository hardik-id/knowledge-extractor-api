"""``manage.py platform_admin list | grant --oid <uuid> | revoke --oid <uuid>``.

For operators. The person must have signed in once. The audit entry has no actor.
"""

import uuid
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.errors import ApiError
from apps.iam import services
from apps.iam.models import PlatformAdmin


class Command(BaseCommand):
    help = "List, grant or revoke platform admins."

    def add_arguments(self, parser: CommandParser) -> None:
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("list", help="Everyone who is a platform admin, and why.")
        for name in ("grant", "revoke"):
            one = sub.add_parser(name)
            one.add_argument("--oid", required=True, type=uuid.UUID)

    def handle(self, *args: Any, **options: Any) -> None:
        action = options["action"]
        if action == "list":
            for oid in sorted(str(o) for o in settings.IAM_PLATFORM_ADMIN_OIDS):
                self.stdout.write(f"{oid}\tsetting")
            for row in PlatformAdmin.objects.select_related("user"):
                self.stdout.write(f"{row.user.oid}\tgranted")
            return
        users = list(get_user_model().objects.filter(oid=options["oid"]))
        if len(users) != 1:
            raise CommandError(
                "No person with this oid has signed in."
                if not users
                else "Several people share this oid; use the Django admin."
            )
        try:
            if action == "grant":
                services.grant_platform_admin(None, users[0].pk)
            else:
                services.revoke_platform_admin(None, users[0].pk)
        except ApiError as error:
            raise CommandError(error.message) from None
        self.stdout.write(f"{action}: done")
