from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import uuid


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_input TEXT NOT NULL,
                    tool_output TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                    FOREIGN KEY(message_id) REFERENCES messages(id)
                )
                """
            )

    def create_conversation(self, conversation_id: str | None = None) -> str:
        conversation_id = conversation_id or str(uuid.uuid4())
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO conversations(id) VALUES (?)", (conversation_id,))
        return conversation_id

    def save_message(self, conversation_id: str, role: str, content: str) -> str:
        message_id = str(uuid.uuid4())
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO messages(id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (message_id, conversation_id, role, content),
            )
        return message_id

    def save_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_name: str,
        tool_input: dict | str,
        tool_output: dict | str | None,
        status: str,
        error: str | None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls(
                    id, conversation_id, message_id, tool_name, tool_input, tool_output, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    conversation_id,
                    message_id,
                    tool_name,
                    json.dumps(tool_input, ensure_ascii=False),
                    json.dumps(tool_output, ensure_ascii=False) if tool_output is not None else None,
                    status,
                    error,
                ),
            )

    def get_messages(self, conversation_id: str) -> list[dict[str, str]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def list_todos(self) -> list[dict[str, str]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT tool_output
                FROM tool_calls
                WHERE tool_name = 'todo_create' AND status = 'success'
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        todos: list[dict[str, str]] = []
        for row in rows:
            if not row["tool_output"]:
                continue
            parsed = json.loads(row["tool_output"])
            if isinstance(parsed, dict):
                todos.append(parsed)
        return todos
