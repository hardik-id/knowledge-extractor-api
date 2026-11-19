from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = "apps.documents"

    def ready(self) -> None:
        from apps.documents.backends import check_settings

        check_settings()
