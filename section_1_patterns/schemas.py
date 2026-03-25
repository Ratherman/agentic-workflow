from typing import Literal

from pydantic import BaseModel


class RouteDecision(BaseModel):
    action_type: Literal["tool", "workflow", "llm"]
    target: str
    reason: str
