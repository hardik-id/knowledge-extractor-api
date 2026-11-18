"""Print a local development access token (``AUTH_MODE=dev`` only).

    uv run python manage.py mint_dev_token [--name ...] [--oid ...] [--ttl ...]

Only the token goes to stdout, so ``$(...)`` works. See docs/auth.md.
"""

import uuid
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.identity import dev_issuer


class Command(BaseCommand):
    help = "Print an access token for the local dev issuer (AUTH_MODE=dev)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--name", default=dev_issuer.DEFAULT_NAME)
        parser.add_argument(
            "--oid",
            default=dev_issuer.DEFAULT_OID,
            help="the person's object id, a UUID; the same oid is the same user",
        )
        parser.add_argument(
            "--ttl",
            type=int,
            default=dev_issuer.DEFAULT_TTL_SECONDS,
            help="seconds the token stays valid (default %(default)s)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.AUTH_MODE != "dev":
            raise CommandError("Dev tokens are only for AUTH_MODE=dev.")
        if options["ttl"] <= 0:
            raise CommandError("--ttl must be a positive number of seconds.")
        try:
            uuid.UUID(options["oid"])
        except ValueError:
            raise CommandError("--oid must be a UUID.") from None
        self.stdout.write(
            dev_issuer.mint_dev_token(
                name=options["name"],
                oid=options["oid"],
                ttl_seconds=options["ttl"],
            )
        )
