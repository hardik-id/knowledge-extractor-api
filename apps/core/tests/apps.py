from django.apps import AppConfig


class CoreTestsConfig(AppConfig):
    """Test-only app holding a small model for testing shared components."""

    name = "apps.core.tests"
    label = "core_tests"
