import pytest
from sqlalchemy import select

from app.core.security import get_password_hash, verify_password
from app.db.session import AsyncSessionLocal
from app.models.task import Task
from app.models.user import User
from app.services.openrouter_service import OpenRouterError, OpenRouterService
from scripts.seed_admin import seed_admin
from tests.conftest import auth_header, login, register


def tool_response(name: str, arguments: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            }
                        }
                    ]
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_admin_seed_is_idempotent_and_never_elevates_or_resets(
    client, monkeypatch
):
    monkeypatch.setenv("ADMIN_NAME", "Seed Admin")
    monkeypatch.setenv("ADMIN_EMAIL", "seed@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "SeedPassword123!")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert await seed_admin() is True
    assert await seed_admin() is False
    async with AsyncSessionLocal() as session:
        admin = await session.scalar(
            select(User).where(User.email == "seed@example.com")
        )
        assert admin.role == "admin"
        assert verify_password("SeedPassword123!", admin.password_hash)

    monkeypatch.setenv("ADMIN_EMAIL", "ordinary@example.com")
    await register(client, "ordinary@example.com")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="non-admin"):
        await seed_admin()
    async with AsyncSessionLocal() as session:
        ordinary = await session.scalar(
            select(User).where(User.email == "ordinary@example.com")
        )
        assert ordinary.role == "user"


@pytest.mark.asyncio
async def test_chatbot_validates_tools_and_scopes_task_access(client, monkeypatch):
    await register(client, "chat-owner@example.com")
    owner_token = await login(client, "chat-owner@example.com")
    task_response = await client.post(
        "/api/v1/tasks",
        headers=auth_header(owner_token),
        json={"title": "Only mine"},
    )
    task_id = task_response.json()["id"]
    await register(client, "chat-other@example.com")
    other_token = await login(client, "chat-other@example.com")

    async def get_foreign_task(self, messages, tools=None, tool_choice=None):
        return tool_response("get_task", f'{{"task_id": {task_id}}}')

    monkeypatch.setattr(OpenRouterService, "chat_completion", get_foreign_task)
    result = await client.post(
        "/api/v1/chatbot/message",
        headers=auth_header(other_token),
        json={"message": "Show me task details"},
    )
    assert result.status_code == 200
    assert "not accessible" in result.json()["response"]

    async def inject_owner_id(self, messages, tools=None, tool_choice=None):
        return tool_response(
            "create_task",
            '{"title": "forged", "owner_id": 1}',
        )

    monkeypatch.setattr(OpenRouterService, "chat_completion", inject_owner_id)
    invalid = await client.post(
        "/api/v1/chatbot/message",
        headers=auth_header(other_token),
        json={"message": "Create a task"},
    )
    assert invalid.status_code == 200
    assert "invalid arguments" in invalid.json()["response"]
    async with AsyncSessionLocal() as session:
        tasks = (await session.scalars(select(Task))).all()
        assert len(tasks) == 1


@pytest.mark.asyncio
async def test_chatbot_requires_user_confirmation_before_deletion(client, monkeypatch):
    await register(client, "delete@example.com")
    token = await login(client, "delete@example.com")
    created = await client.post(
        "/api/v1/tasks",
        headers=auth_header(token),
        json={"title": "Confirm deletion"},
    )
    task_id = created.json()["id"]

    async def fake_delete_call(self, messages, tools=None, tool_choice=None):
        return tool_response(
            "delete_task", f'{{"task_id": {task_id}, "confirmed": true}}'
        )

    monkeypatch.setattr(OpenRouterService, "chat_completion", fake_delete_call)
    first = await client.post(
        "/api/v1/chatbot/message",
        headers=auth_header(token),
        json={"message": f"Delete task {task_id}"},
    )
    assert first.status_code == 200
    assert "confirm delete task" in first.json()["response"]
    assert first.json()["tasks_affected"] is None
    assert (
        await client.get(f"/api/v1/tasks/{task_id}", headers=auth_header(token))
    ).status_code == 200

    confirmed = await client.post(
        "/api/v1/chatbot/message",
        headers=auth_header(token),
        json={"message": f"confirm delete task {task_id}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["tasks_affected"] == [task_id]
    assert (
        await client.get(f"/api/v1/tasks/{task_id}", headers=auth_header(token))
    ).status_code == 404


@pytest.mark.asyncio
async def test_chatbot_provider_failure_is_explicit(client, monkeypatch):
    await register(client, "provider@example.com")
    token = await login(client, "provider@example.com")

    async def fail(self, messages, tools=None, tool_choice=None):
        raise OpenRouterError("provider unavailable", status_code=503)

    monkeypatch.setattr(OpenRouterService, "chat_completion", fail)
    response = await client.post(
        "/api/v1/chatbot/message",
        headers=auth_header(token),
        json={"message": "List my tasks"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "The chatbot service could not complete the request."
