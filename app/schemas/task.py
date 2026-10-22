from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TaskTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class TaskBase(BaseModel):
    title: TaskTitle
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["todo", "in_progress", "completed"] = "todo"
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: datetime | None = None

    model_config = {"extra": "forbid"}


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: TaskTitle | None = None
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["todo", "in_progress", "completed"] | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_date: datetime | None = None

    model_config = {"extra": "forbid"}

    @field_validator("title", "status", "priority")
    @classmethod
    def reject_null_non_nullable_fields(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field cannot be null")
        return value

    @model_validator(mode="after")
    def require_updated_field(self) -> "TaskUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one task field must be provided")
        return self


class TaskOut(TaskBase):
    id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskList(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    size: int
    pages: int