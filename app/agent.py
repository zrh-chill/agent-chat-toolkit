from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from typing import Any

from pydantic import ValidationError

from app.database import Database
from app.llm import LLMClientError, LLMResponse
from app.models import AgentResponse, StreamEvent, ToolCallRecord
from app.tools import ToolExecutionError, ToolRegistry


SYSTEM_PROMPT = """
You are an assistant that can use tools when helpful.
Use tools for arithmetic, todo creation/listing, and weather lookup.
After all needed tools are done, produce a compact JSON object with keys:
answer, intent, tool_used, confidence.
Do not wrap the JSON in markdown fences.
Confidence must be a number between 0 and 1.
"""


class AgentService:
    def __init__(self, database: Database, llm_client: Any) -> None:
        self.database = database
        self.llm_client = llm_client
        self.tools = ToolRegistry(database)
        self.max_tool_rounds = 4

    async def run(self, message: str, conversation_id: str | None = None) -> AgentResponse:
        collected: list[StreamEvent] = []
        async for event in self.run_stream(message, conversation_id):
            collected.append(event)
        for event in reversed(collected):
            if event.event == "final":
                return AgentResponse.model_validate(event.data["response"])
        raise RuntimeError("Agent did not produce a final response.")

    async def run_stream(
        self, message: str, conversation_id: str | None = None
    ) -> AsyncGenerator[StreamEvent, None]:
        conversation_id = self.database.create_conversation(conversation_id)
        history = self.database.get_messages(conversation_id)
        user_message_id = self.database.save_message(conversation_id, "user", message)

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        tool_records: list[ToolCallRecord] = []

        current_response: LLMResponse | None = None
        for _ in range(self.max_tool_rounds):
            try:
                current_response = await self.llm_client.complete(
                    messages=messages,
                    tools=self.tools.openai_schemas(),
                )
            except LLMClientError as exc:
                yield StreamEvent(event="error", data={"message": f"LLM request failed: {exc}"})
                raise

            if not current_response.tool_calls:
                break

            assistant_tool_message = {
                "role": "assistant",
                "content": current_response.content or "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                        },
                    }
                    for tool_call in current_response.tool_calls
                ],
            }
            messages.append(assistant_tool_message)

            for tool_call in current_response.tool_calls:
                yield StreamEvent(
                    event="tool_start",
                    data={"tool": tool_call.name, "input": tool_call.arguments},
                )
                result: dict[str, Any] | None = None
                status = "success"
                error: str | None = None
                try:
                    result = self.tools.execute(tool_call.name, tool_call.arguments)
                except ToolExecutionError as exc:
                    status = "error"
                    error = str(exc)
                    result = {"error": error}

                record = ToolCallRecord(
                    tool=tool_call.name,
                    input=tool_call.arguments,
                    output=result,
                    status=status,
                    error=error,
                )
                tool_records.append(record)
                self.database.save_tool_call(
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    tool_name=record.tool,
                    tool_input=record.input,
                    tool_output=record.output,
                    status=record.status,
                    error=record.error,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                yield StreamEvent(
                    event="tool_end",
                    data={
                        "tool": tool_call.name,
                        "output": result,
                        "status": status,
                        "error": error,
                    },
                )

        if current_response is None:
            raise RuntimeError("Agent did not receive a model response.")

        final_response = self._build_response(
            content=current_response.content,
            conversation_id=conversation_id,
            tool_records=tool_records,
        )

        self.database.save_message(conversation_id, "assistant", final_response.answer)
        for char in final_response.answer:
            yield StreamEvent(event="message_delta", data={"delta": char})
        yield StreamEvent(event="final", data={"response": final_response.model_dump()})

    def _build_response(
        self,
        content: str,
        conversation_id: str,
        tool_records: list[ToolCallRecord],
    ) -> AgentResponse:
        payload = self._parse_structured_content(content)
        if "tool_used" not in payload or not payload["tool_used"]:
            payload["tool_used"] = [record.tool for record in tool_records]
        if "confidence" not in payload:
            payload["confidence"] = 0.5
        payload["tool_calls"] = [record.model_dump() for record in tool_records]
        payload["conversation_id"] = conversation_id
        try:
            return AgentResponse.model_validate(payload)
        except ValidationError:
            return AgentResponse(
                answer=payload.get("answer", content.strip() or "I could not generate a valid response."),
                intent=payload.get("intent", "unknown"),
                tool_used=[record.tool for record in tool_records],
                confidence=min(max(float(payload.get("confidence", 0.5)), 0.0), 1.0),
                tool_calls=tool_records,
                conversation_id=conversation_id,
            )

    def _parse_structured_content(self, content: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        return {
            "answer": content.strip() or "I could not generate a response.",
            "intent": "general_chat",
            "tool_used": [],
            "confidence": 0.5,
        }
