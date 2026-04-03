from pydantic import BaseModel, Field
from typing import Any


class TransformStage(BaseModel):
    transform: str
    params: dict[str, Any] = Field(default_factory=dict)
    block_id: str | None = None  # filled by compiler


class TransformPlan(BaseModel):
    stages: list[TransformStage] = Field(default_factory=list)
