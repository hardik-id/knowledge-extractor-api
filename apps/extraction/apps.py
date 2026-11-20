from django.apps import AppConfig


class ExtractionConfig(AppConfig):
    name = "apps.extraction"

    def ready(self) -> None:
        from apps.extraction import template_registry
        from apps.extraction.extractors import check_settings

        check_settings()
        template_registry.list_templates()  # a broken template file fails here
