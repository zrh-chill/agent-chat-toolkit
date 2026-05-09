from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent import AgentService
from app.database import Database
from app.main import create_app
from app.models import AgentResponse


class FakeLLMClient:
    async def complete(self, messages, tools=None):
        last_user_message = ""
        for message in reversed(messages):
            if message["role"] == "user":
                last_user_message = message["content"]
                break

        if tools:
            if "235 * 18" in last_user_message:
                return FakeResponse(
                    content="",
                    tool_calls=[
                        FakeToolCall("call_calc", "calculator", {"expression": "235 * 18"}),
                        FakeToolCall("call_todo", "todo_create", {"title": "记录计算结果 4230"}),
                    ],
                )
            if "天气" in last_user_message:
                return FakeResponse(
                    content="",
                    tool_calls=[FakeToolCall("call_weather", "fake_weather", {"city": "北京"})],
                )
            if "待办列表" in last_user_message:
                return FakeResponse(
                    content="",
                    tool_calls=[FakeToolCall("call_todo_list", "todo_list", {})],
                )
            if "坏掉" in last_user_message:
                return FakeResponse(
                    content="",
                    tool_calls=[FakeToolCall("call_bad_calc", "calculator", {"expression": "1 / 0"})],
                )
            return FakeResponse(
                content=json.dumps(
                    {
                        "answer": "这是一条普通回复。",
                        "intent": "general_chat",
                        "tool_used": [],
                        "confidence": 0.88,
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            )

        tool_names = []
        tool_payloads = []
        for message in messages:
            if message["role"] == "tool":
                tool_payloads.append(json.loads(message["content"]))
        for message in messages:
            if message["role"] == "assistant" and message.get("tool_calls"):
                tool_names.extend(call["function"]["name"] for call in message["tool_calls"])

        answer = "工具执行完成。"
        intent = "tool_usage"
        if "fake_weather" in tool_names:
            weather = tool_payloads[-1]
            answer = f"{weather['city']}当前天气{weather['condition']}，气温{weather['temperature_c']}度。"
            intent = "weather_lookup"
        elif "todo_list" in tool_names:
            items = tool_payloads[-1]["items"]
            answer = f"当前共有 {len(items)} 个待办事项。"
            intent = "todo_list"
        elif "calculator" in tool_names and "todo_create" in tool_names:
            answer = "计算结果是 4230，我已经帮你创建了待办事项。"
            intent = "calculate_and_create_todo"
        elif "calculator" in tool_names:
            payload = tool_payloads[-1]
            if "error" in payload:
                answer = f"计算失败：{payload['error']}"
                intent = "tool_error"

        return FakeResponse(
            content=json.dumps(
                {
                    "answer": answer,
                    "intent": intent,
                    "tool_used": tool_names,
                    "confidence": 0.91,
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict) -> None:
        self.id = call_id
        self.name = name
        self.arguments = arguments


class FakeResponse:
    def __init__(self, content: str, tool_calls: list[FakeToolCall]) -> None:
        self.content = content
        self.tool_calls = tool_calls


def build_client(tmp_path: Path) -> TestClient:
    app = create_app()
    database = Database(str(tmp_path / "test.db"))
    database.init()
    app.state.database = database
    app.state.agent_service = AgentService(database=database, llm_client=FakeLLMClient())
    return TestClient(app)


def test_chat_without_tool_call(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post("/chat", json={"message": "你好"})
    assert response.status_code == 200
    payload = AgentResponse.model_validate(response.json())
    assert payload.answer == "这是一条普通回复。"
    assert payload.tool_calls == []


def test_chat_with_multi_tool_chain(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post("/chat", json={"message": "帮我计算 235 * 18，然后生成一个待办事项"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "calculate_and_create_todo"
    assert payload["tool_used"] == ["calculator", "todo_create"]
    assert len(payload["tool_calls"]) == 2


def test_todo_list_reads_persisted_items(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    first = client.post("/chat", json={"message": "帮我计算 235 * 18，然后生成一个待办事项"})
    conversation_id = first.json()["conversation_id"]
    response = client.post("/chat", json={"message": "帮我看看待办列表", "conversation_id": conversation_id})
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "todo_list"
    assert payload["tool_calls"][0]["output"]["items"][0]["title"] == "记录计算结果 4230"


def test_tool_error_is_controlled(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post("/chat", json={"message": "帮我把这个计算坏掉"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "tool_error"
    assert payload["tool_calls"][0]["status"] == "error"
    assert "Division by zero" in payload["tool_calls"][0]["error"]


def test_stream_endpoint_emits_expected_events(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    with client.stream("POST", "/chat/stream", json={"message": "北京天气怎么样？"}) as response:
        assert response.status_code == 200
        body = "".join(chunk if isinstance(chunk, str) else chunk.decode() for chunk in response.iter_text())
    assert "event: tool_start" in body
    assert "event: tool_end" in body
    assert "event: message_delta" in body
    assert "event: final" in body
