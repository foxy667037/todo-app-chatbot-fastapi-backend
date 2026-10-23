import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.api.v1.endpoints import auth, users, tasks, chatbot

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    from app.db.session import engine

    await engine.dispose()


app = FastAPI(title="Todo Management API", version="1.0.0", lifespan=lifespan)


class LimitContentLengthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if (
            content_length
            and content_length.isdecimal()
            and int(content_length) > 1_048_576
        ):
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds the 1 MiB limit"},
            )
        return await call_next(request)


app.add_middleware(LimitContentLengthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_request_content_length(request, call_next):
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdecimal()
        and int(content_length) > 1_048_576
    ):
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds the 1 MiB limit"},
        )
    return await call_next(request)


app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(chatbot.router, prefix="/api/v1/chatbot", tags=["chatbot"])


@app.get("/")
async def root():
    return {"status": "ok", "message": "Todo Management API is running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness():
    from app.db.session import engine

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": "Database unavailable"},
        )
    return {"status": "ready"}
