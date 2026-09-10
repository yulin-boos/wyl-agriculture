"""Validated administrator knowledge template input."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator



ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")]
    label: ShortText
    crop: ShortText
    crop_zh: ShortText
    disease_zh: ShortText
    title: ShortText
    source_org: ShortText
    source_url: HttpUrl = Field(max_length=2048)
    source_updated: str = Field(default="", max_length=100)
    content: str = Field(min_length=20, max_length=20000)
    tags: list[ShortText] = Field(min_length=1, max_length=30)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tags))


class DuplicateKnowledgeError(ValueError):
    pass

