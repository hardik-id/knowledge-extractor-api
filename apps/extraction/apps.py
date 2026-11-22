from django.apps import AppConfig
from django.core import checks


class ExtractionConfig(AppConfig):
    name = "apps.extraction"

    def ready(self) -> None:
        from apps.extraction import template_registry
        from apps.extraction.checks import check_llm_settings
        from apps.extraction.extractors import check_settings

        check_settings()
        checks.register(check_llm_settings)
        template_registry.list_templates()  # a broken template file fails here
