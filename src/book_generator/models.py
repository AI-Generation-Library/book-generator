from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BookConfig(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=20000)
    audience: str = Field(default="기초부터 배우는 독자", min_length=1, max_length=1000)
    language: str = Field(default="한국어", min_length=1, max_length=100)
    outline: str = Field(default="", max_length=30000)
    references: str = Field(default="", max_length=30000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    chapter_count: int = Field(default=8, ge=1, le=60)
    provider: Literal["openai", "claude", "gemini"] = "openai"
    model: str = Field(default="", max_length=120)
    workspace_id: str = Field(default="", max_length=120)
    max_output_tokens: int = Field(default=6000, ge=512, le=32000)
    output_budget: int = Field(default=60000, ge=512, le=2000000)
    demo: bool = False

    @field_validator("id")
    @classmethod
    def slug(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("id에는 소문자 영문, 숫자와 하이픈만 사용할 수 있습니다.")
        if value.upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        }:
            raise ValueError("운영체제가 예약한 이름은 사용할 수 없습니다.")
        return value

    @field_validator("model", "workspace_id")
    @classmethod
    def identifier(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("모델과 Workspace ID에는 영문, 숫자, 점, 하이픈, 밑줄만 사용할 수 있습니다.")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        if any(not tag.strip() or len(tag) > 100 for tag in values):
            raise ValueError("태그는 1~100자의 문자열이어야 합니다.")
        return list(dict.fromkeys(tag.strip() for tag in values))

    def ensure_ready(self) -> None:
        if not self.demo and not self.model:
            raise ValueError("사용할 제공자의 모델 ID를 입력하세요.")


class ChapterPlan(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1500)
    objectives: list[str] = Field(min_length=1, max_length=8)


class PartPlan(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    chapters: list[ChapterPlan] = Field(min_length=1, max_length=60)


class BookPlan(StrictModel):
    description: str = Field(min_length=1, max_length=2000)
    parts: list[PartPlan] = Field(min_length=1, max_length=20)

    def chapters(self) -> list[tuple[int, ChapterPlan]]:
        return [(number, chapter) for number, part in enumerate(self.parts, 1) for chapter in part.chapters]


def plan_schema() -> dict:
    """The common schema uses only a small subset supported by Responses structured outputs."""
    schema = BookPlan.model_json_schema()

    def simplify(value):
        if isinstance(value, dict):
            return {
                key: (
                    {name: simplify(schema) for name, schema in item.items()}
                    if key == "properties"
                    else simplify(item)
                )
                for key, item in value.items()
                if key not in {"title", "minLength", "maxLength", "minItems", "maxItems"}
            }
        if isinstance(value, list):
            return [simplify(item) for item in value]
        return value

    return simplify(schema)
