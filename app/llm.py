from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - depends on local environment
    AsyncOpenAI = None


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[LLMToolCall]


class LLMClientError(Exception):
    """Raised when the LLM client fails."""


class OpenAIChatClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        if AsyncOpenAI is None:
            raise LLMClientError(
                "The openai package is not installed. Run `pip install -r requirements.txt` first."
            )
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.2,
            )
        except Exception as exc:  # pragma: no cover - network/provider failures
            raise LLMClientError(str(exc)) from exc

        message = response.choices[0].message
        tool_calls: list[LLMToolCall] = []
        for tool_call in message.tool_calls or []:
            arguments = tool_call.function.arguments
            parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            tool_calls.append(
                LLMToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=parsed_arguments,
                )
            )
        return LLMResponse(content=message.content or "", tool_calls=tool_calls)
