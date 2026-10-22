from pydantic import BaseModel, Field


class ChatbotMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

    model_config = {"extra": "forbid"}


class ChatbotResponse(BaseModel):
    response: str
    tasks_affected: list[int] | None = None