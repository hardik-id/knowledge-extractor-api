from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"

    def ready(self) -> None:
        # Django has configured logging by now, which dropped the root handlers
        # that telemetry set up before django.setup().
        from apps.core.telemetry import attach_log_handler

        attach_log_handler()
