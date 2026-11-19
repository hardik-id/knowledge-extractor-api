"""The schema of a definition, for any tool that takes one."""

import pytest
from pydantic import ValidationError

from apps.assistant.agents.openai_sdk.tools._definition_schema import DefinitionArgs
from apps.assistant.tests.test_scripted import adr


def test_a_definition_fits_and_unknown_keys_are_refused() -> None:
    assert DefinitionArgs.model_validate(adr()).model_dump() == adr()
    with pytest.raises(ValidationError):
        DefinitionArgs.model_validate({**adr(), "extra": 1})
