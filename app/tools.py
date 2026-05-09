from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Callable
import uuid

from app.database import Database


class ToolExecutionError(Exception):
    """Raised when a tool cannot complete successfully."""


def safe_calculate(expression: str) -> float | int:
    allowed_nodes = {
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Constant,
        ast.FloorDiv,
    }

    def _eval(node: ast.AST) -> float | int:
        if type(node) not in allowed_nodes:
            raise ToolExecutionError("Unsupported expression.")
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp):
            value = _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
        raise ToolExecutionError("Invalid expression.")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree)
    except ZeroDivisionError as exc:
        raise ToolExecutionError("Division by zero is not allowed.") from exc
    except SyntaxError as exc:
        raise ToolExecutionError("Expression syntax is invalid.") from exc
    return int(result) if isinstance(result, float) and result.is_integer() else result


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


class ToolRegistry:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._tools = {
            "calculator": ToolDefinition(
                name="calculator",
                description="Calculate a simple arithmetic expression.",
                parameters={
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Arithmetic expression such as 235 * 18",
                        }
                    },
                    "required": ["expression"],
                    "additionalProperties": False,
                },
                handler=self._calculator,
            ),
            "todo_create": ToolDefinition(
                name="todo_create",
                description="Create a todo item for the current user.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Todo title"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
                handler=self._todo_create,
            ),
            "todo_list": ToolDefinition(
                name="todo_list",
                description="List all todo items created so far.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=self._todo_list,
            ),
            "fake_weather": ToolDefinition(
                name="fake_weather",
                description="Return a mocked weather response for a city.",
                parameters={
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"},
                    },
                    "required": ["city"],
                    "additionalProperties": False,
                },
                handler=self._fake_weather,
            ),
        }

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            raise ToolExecutionError(f"Unknown tool: {name}")
        return self._tools[name].handler(**arguments)

    def _calculator(self, expression: str) -> dict[str, Any]:
        return {"result": safe_calculate(expression)}

    def _todo_create(self, title: str) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ToolExecutionError("Todo title cannot be empty.")
        return {"id": str(uuid.uuid4()), "title": title}

    def _todo_list(self) -> dict[str, Any]:
        return {"items": self.database.list_todos()}

    def _fake_weather(self, city: str) -> dict[str, Any]:
        city = city.strip()
        if not city:
            raise ToolExecutionError("City cannot be empty.")
        return {
            "city": city,
            "condition": "Sunny",
            "temperature_c": 26,
            "humidity": 48,
        }
