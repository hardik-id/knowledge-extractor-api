from django.apps import AppConfig


class ExtractionConfig(AppConfig):
    name = "apps.extraction"

    def ready(self) -> None:
        from apps.extraction.extractors import check_settings

        check_settings()
