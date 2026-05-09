from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.agent import AgentService
from app.config import get_settings
from app.database import Database
from app.llm import LLMClientError, OpenAIChatClient
from app.models import AgentResponse, ChatRequest, StreamEvent


BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    settings = get_settings()
    database = Database(settings.sqlite_path)
    database.init()

    app = FastAPI(title="agent-chat-toolkit")
    app.state.database = database

    if settings.openai_api_key:
        app.state.agent_service = AgentService(
            database=database,
            llm_client=OpenAIChatClient(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
            ),
        )
    else:
        app.state.agent_service = None

    def get_agent_service() -> AgentService:
        service = app.state.agent_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="LLM client is not configured. Please set OPENAI_API_KEY in .env.",
            )
        return service

    @app.get("/", response_class=FileResponse)
    async def index() -> FileResponse:
        return FileResponse(BASE_DIR / "static" / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=AgentResponse)
    async def chat(request: ChatRequest, agent_service: AgentService = Depends(get_agent_service)) -> AgentResponse:
        try:
            return await agent_service.run(request.message, request.conversation_id)
        except LLMClientError as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    @app.post("/chat/stream")
    async def chat_stream(
        request: ChatRequest,
        agent_service: AgentService = Depends(get_agent_service),
    ) -> StreamingResponse:
        async def event_source() -> AsyncGenerator[str, None]:
            try:
                async for event in agent_service.run_stream(request.message, request.conversation_id):
                    yield format_sse(event)
            except LLMClientError as exc:
                yield format_sse(StreamEvent(event="error", data={"message": f"LLM request failed: {exc}"}))

        return StreamingResponse(event_source(), media_type="text/event-stream")

    return app


def format_sse(event: StreamEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


app = create_app()
