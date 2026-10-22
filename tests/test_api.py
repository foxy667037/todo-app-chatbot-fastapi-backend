import pytest
from sqlalchemy import select

from app.core.security import get_password_hash, verify_password
from app.db.session import AsyncSessionLocal
from app.models.task import Task
from app.models.user import User
from tests.conftest import auth_header, login, register


async def create_admin(email: str = "admin@example.com") -> User:
    async with AsyncSessionLocal() as session:
        admin = User(
            full_name="Test Admin",
            email=email,
            password_hash=get_password_hash("AdminPassword123!"),
            role="admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin


@pytest.mark.asyncio
async def test_registration_login_jwt_and_public_role(client):
    denied = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Attacker",
            "email": "attacker@example.com",
            "password": "StrongPassword123!",
            "role": "admin",
        },
    )
    assert denied.status_code == 422

    user = await register(client, "person@example.com")
    assert user["role"] == "user"
    async with AsyncSessionLocal() as session:
        stored = await session.scalar(
            select(User).where(User.email == "person@example.com")
        )
        assert stored is not None
        assert stored.password_hash != "TestPassword123!"
        assert verify_password("TestPassword123!", stored.password_hash)

    token = await login(client, "PERSON@example.com")
    me = await client.get("/api/v1/auth/me", headers=auth_header(token))
    assert me.status_code == 200
    assert me.json()["email"] == "person@example.com"
    invalid = await client.get(
        "/api/v1/auth/me", headers=auth_header("not-a-valid-token")
    )
    assert invalid.status_code == 401


@pytest.mark.asyncio
async def test_inactive_user_cannot_login_or_use_token(client):
    user = await register(client, "inactive@example.com")
    token = await login(client, "inactive@example.com")
    async with AsyncSessionLocal() as session:
        stored = await session.get(User, user["id"])
        stored.is_active = False
        await session.commit()

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "TestPassword123!"},
    )
    assert login_response.status_code == 403
    profile = await client.get("/api/v1/auth/me", headers=auth_header(token))
    assert profile.status_code == 401


@pytest.mark.asyncio
async def test_task_crud_and_ownership_isolation(client):
    owner = await register(client, "owner@example.com")
    owner_token = await login(client, "owner@example.com")
    other_token = await login(
        client,
        (await register(client, "other@example.com"))["email"],
    )
    headers = auth_header(owner_token)
    created = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Private task", "priority": "high"},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["owner_id"] == owner["id"]

    # Ownership fields are rejected rather than trusted or silently applied.
    invalid_create = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Forged", "owner_id": owner["id"] + 1},
    )
    assert invalid_create.status_code == 422
    assert (await client.get(f"/api/v1/tasks/{task['id']}", headers=auth_header(other_token))).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers=auth_header(other_token),
            json={"title": "Hijacked"},
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/tasks/{task['id']}", headers=auth_header(other_token)
        )
    ).status_code == 404

    updated = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"status": "completed", "title": "Finished"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    assert (
        await client.patch(
            f"/api/v1/tasks/{task['id']}", headers=headers, json={}
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers=headers,
            json={"status": None},
        )
    ).status_code == 422
    deleted = await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (
        await client.get(f"/api/v1/tasks/{task['id']}", headers=headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_admin_can_list_users_and_manage_all_tasks(client):
    await create_admin()
    admin_token = await login(client, "admin@example.com", "AdminPassword123!")
    user = await register(client, "member@example.com")
    user_token = await login(client, user["email"])
    task = await client.post(
        "/api/v1/tasks",
        headers=auth_header(user_token),
        json={"title": "Member task"},
    )
    assert task.status_code == 201

    users = await client.get("/api/v1/users", headers=auth_header(admin_token))
    assert users.status_code == 200
    assert len(users.json()) == 2
    assert (
        await client.get("/api/v1/users", headers=auth_header(user_token))
    ).status_code == 403
    admin_view = await client.get(
        f"/api/v1/tasks/{task.json()['id']}", headers=auth_header(admin_token)
    )
    assert admin_view.status_code == 200
    updated = await client.patch(
        f"/api/v1/tasks/{task.json()['id']}",
        headers=auth_header(admin_token),
        json={"title": "Admin updated"},
    )
    assert updated.status_code == 200


@pytest.mark.asyncio
async def test_task_pagination_search_and_filters(client):
    await register(client, "filters@example.com")
    token = await login(client, "filters@example.com")
    headers = auth_header(token)
    payloads = [
        {"title": "Needle in title", "description": "unrelated", "priority": "high"},
        {"title": "unrelated title", "description": "Needle in description", "priority": "high"},
        {"title": "Other task", "priority": "low"},
    ]
    for payload in payloads:
        response = await client.post("/api/v1/tasks", headers=headers, json=payload)
        assert response.status_code == 201

    response = await client.get(
        "/api/v1/tasks?search=nEeDlE&priority=high&page=1&size=1",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["pages"] == 2
    assert len(response.json()["items"]) == 1
    invalid_filter = await client.get(
        "/api/v1/tasks?status=unknown", headers=headers
    )
    assert invalid_filter.status_code == 422
