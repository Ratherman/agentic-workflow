from typing import Literal

from pydantic import BaseModel


class RouteDecision(BaseModel):
    action_type: Literal["tool", "workflow", "skill", "llm"]
    target: str
    reason: str
