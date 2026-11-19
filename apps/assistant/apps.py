from django.apps import AppConfig
from django.core import checks


class AssistantConfig(AppConfig):
    name = "apps.assistant"

    def ready(self) -> None:
        from apps.assistant.agents.registry import check_settings
        from apps.assistant.checks import check_llm_settings

        check_settings()
        checks.register(check_llm_settings)
