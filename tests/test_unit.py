from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.security import create_access_token, decode_token
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskUpdate
from app.schemas.user import UserCreate
from app.services.auth_service import authenticate_user
from app.services.chatbot_service import (
    ChatbotService,
    _DELETE_CONFIRMATION,
)
from app.services.openrouter_service import OpenRouterError, OpenRouterService
from app.services.task_service import delete_task, update_task


@pytest.mark.asyncio
async def test_root_endpoint_reports_server_running():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "Todo Management API is running",
    }


def test_settings_require_postgresql_and_secure_jwt_secret():
    base = {"database_url": "postgresql+psycopg://user:pass@localhost/todo"}
    with pytest.raises(ValidationError):
        Settings(**base, jwt_secret_key="weak")
    with pytest.raises(ValidationError):
        Settings(
            database_url="sqlite:///todo.db",
            jwt_secret_key="a-long-enough-test-secret-value-123",
        )
    with pytest.raises(ValidationError):
        Settings(
            **base,
            jwt_secret_key="a-long-enough-test-secret-value-123",
            jwt_algorithm="none",
        )
    with pytest.raises(ValidationError):
        Settings(
            **base,
            jwt_secret_key="a-long-enough-test-secret-value-123",
            cors_origins="*",
        )


def test_neon_postgres_url_normalization_and_production_tls():
    settings = Settings(
        database_url="postgresql://user:password@ep-example-pooler.neon.tech/app?sslmode=require",
        jwt_secret_key="a-long-enough-test-secret-value-123",
        environment="production",
        cors_origins="https://todo.example.com",
    )
    assert settings.database_url.startswith("postgresql+psycopg://")

    with pytest.raises(ValidationError, match="sslmode"):
        Settings(
            database_url="postgresql://user:password@ep-example.neon.tech/app",
            jwt_secret_key="a-long-enough-test-secret-value-123",
            environment="production",
            cors_origins="https://todo.example.com",
        )
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            database_url="postgresql://user:password@ep-example.neon.tech/app?sslmode=require",
            jwt_secret_key="a-long-enough-test-secret-value-123",
            environment="production",
            cors_origins="http://todo.example.com",
        )


@pytest.mark.asyncio
async def test_database_readiness_failure_does_not_expose_connection_details(
    monkeypatch,
):
    class BrokenConnection:
        async def __aenter__(self):
            raise SQLAlchemyError("sensitive database URL")

        async def __aexit__(self, *_args):
            return None

    class BrokenEngine:
        def connect(self):
            return BrokenConnection()

    monkeypatch.setattr("app.db.session.engine", BrokenEngine())

    from app.main import readiness

    response = await readiness()

    assert response.status_code == 503
    assert b"Database unavailable" in response.body
    assert b"sensitive database URL" not in response.body


def test_jwt_expiration_and_signature_validation():
    token = create_access_token({"sub": "9"})
    assert decode_token(token)["sub"] == "9"
    assert decode_token(token + "invalid") is None
    assert decode_token(
        create_access_token({"sub": "9"}, expires_delta=timedelta(seconds=-1))
    ) is None


def test_public_registration_forbids_role_and_requires_strong_password():
    with pytest.raises(ValidationError):
        UserCreate(
            full_name="Example",
            email="example@example.com",
            password="StrongPassword123!",
            role="admin",
        )
    with pytest.raises(ValidationError):
        UserCreate(
            full_name="Example",
            email="example@example.com",
            password="short",
        )


@pytest.mark.asyncio
async def test_inactive_user_is_rejected_during_password_authentication(monkeypatch):
    inactive_user = User(
        id=4,
        email="inactive@example.com",
        is_active=False,
        password_hash="unused",
    )
    monkeypatch.setattr(
        "app.services.auth_service.get_user_by_email",
        AsyncMock(return_value=inactive_user),
    )

    with pytest.raises(HTTPException) as error:
        await authenticate_user(None, "inactive@example.com", "password")

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_chatbot_task_read_does_not_report_a_mutation(monkeypatch):
    task = Task(
        id=12,
        owner_id=1,
        title="Read-only task",
        status="todo",
        priority="medium",
    )
    monkeypatch.setattr(
        "app.services.chatbot_service.get_task_accessible",
        AsyncMock(return_value=task),
    )
    monkeypatch.setattr(
        OpenRouterService,
        "chat_completion",
        AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "get_task",
                                        "arguments": '{"task_id": 12}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ),
    )
    service = ChatbotService(
        session=None,
        current_user=User(id=1, role="user"),
        openrouter=OpenRouterService(api_key="test", model="test"),
    )

    result = await service.handle_message("Show me task 12")

    assert "Read-only task" in result["response"]
    assert result["tasks_affected"] is None


def test_task_patch_rejects_empty_or_null_non_nullable_fields():
    with pytest.raises(ValidationError):
        TaskUpdate()
    with pytest.raises(ValidationError):
        TaskUpdate(title=None)
    with pytest.raises(ValidationError):
        TaskUpdate(status=None)
    with pytest.raises(ValidationError):
        TaskUpdate(priority=None)


@pytest.mark.asyncio
async def test_chatbot_rejects_extra_tool_fields_before_database_access():
    service = ChatbotService(session=None, current_user=None, openrouter=None)
    with pytest.raises(ValidationError):
        await service._execute_tool(
            "create_task", {"title": "Forged", "owner_id": 10}
        )


@pytest.mark.asyncio
async def test_task_mutation_services_recheck_ownership():
    user = User(id=1, role="user")
    foreign_task = Task(id=7, owner_id=2, title="Private task")
    with pytest.raises(HTTPException) as update_error:
        await update_task(None, foreign_task, TaskUpdate(title="Overwritten"), user)
    assert update_error.value.status_code == 404
    with pytest.raises(HTTPException) as delete_error:
        await delete_task(None, foreign_task, user)
    assert delete_error.value.status_code == 404


def test_delete_confirmation_requires_exact_targeted_command():
    assert _DELETE_CONFIRMATION.fullmatch("confirm delete task 17")
    assert _DELETE_CONFIRMATION.fullmatch("CONFIRM deleting task #17!")
    assert _DELETE_CONFIRMATION.fullmatch("yes") is None
    assert _DELETE_CONFIRMATION.fullmatch("confirm delete task 17 and 18") is None


@pytest.mark.asyncio
async def test_openrouter_unconfigured_key_fails_without_network():
    service = OpenRouterService(api_key="", model="test", base_url="https://example.com")
    with pytest.raises(OpenRouterError) as error:
        await service.chat_completion([{"role": "user", "content": "hello"}])
    assert error.value.status_code == 503
    await service.close()


@pytest.mark.asyncio
async def test_openrouter_rate_limit_and_malformed_response_are_explicit():
    async def rate_limited(_request):
        return httpx.Response(429, json={"error": "rate limited"})

    service = OpenRouterService(
        api_key="test-key",
        model="test",
        base_url="https://openrouter.test",
    )
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(rate_limited),
        base_url="https://openrouter.test",
    )
    with pytest.raises(OpenRouterError) as error:
        await service.chat_completion([{"role": "user", "content": "hello"}])
    assert error.value.status_code == 503
    await service.close()

    async def malformed(_request):
        return httpx.Response(200, content=b"{not-json")

    service = OpenRouterService(
        api_key="test-key",
        model="test",
        base_url="https://openrouter.test",
    )
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(malformed),
        base_url="https://openrouter.test",
    )
    with pytest.raises(OpenRouterError) as error:
        await service.chat_completion([{"role": "user", "content": "hello"}])
    assert "invalid response" in str(error.value)
    await service.close()
