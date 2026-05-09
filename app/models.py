from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = None


class ToolCallRecord(BaseModel):
    tool: str
    input: dict[str, Any] | str
    output: dict[str, Any] | str | None = None
    status: str = "success"
    error: str | None = None


class AgentResponse(BaseModel):
    answer: str
    intent: str
    tool_used: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    tool_calls: list[ToolCallRecord]
    conversation_id: str


class StreamEvent(BaseModel):
    event: str
    data: dict[str, Any]
