from django.apps import AppConfig


class IamConfig(AppConfig):
    name = "apps.iam"

    def ready(self) -> None:
        from . import checks  # noqa: F401  (registers the system check)
