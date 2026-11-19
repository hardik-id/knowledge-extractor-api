from django.apps import AppConfig


class AssistantConfig(AppConfig):
    name = "apps.assistant"

    def ready(self) -> None:
        from apps.assistant.agents.registry import check_settings

        check_settings()
