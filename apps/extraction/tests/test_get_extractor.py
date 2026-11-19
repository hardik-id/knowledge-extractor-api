import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.extraction.extractors import check_settings, get_extractor
from apps.extraction.extractors.base import Definition, RawRecord
from apps.extraction.extractors.scripted import ScriptedExtractor


class FakeExtractor:
    def extract(
        self, text: str, definition: Definition, examples: object = ()
    ) -> list[RawRecord]:
        return [RawRecord("rt-fake", None)]


def test_the_default_is_the_scripted_extractor() -> None:
    assert isinstance(get_extractor(), ScriptedExtractor)


def test_a_dotted_path_names_a_class(settings: object) -> None:
    settings.EXTRACTOR = f"{__name__}.FakeExtractor"  # type: ignore[attr-defined]
    extractor = get_extractor()
    assert isinstance(extractor, FakeExtractor)
    assert extractor.extract("", Definition(1, "", []))[0].record_type_id == "rt-fake"


@pytest.mark.parametrize("value", ["gpt", "", "apps.extraction.nothing.Missing"])
def test_an_unknown_value_stops_the_app(settings: object, value: str) -> None:
    settings.EXTRACTOR = value  # type: ignore[attr-defined]
    with pytest.raises(ImproperlyConfigured, match="EXTRACTOR"):
        check_settings()
