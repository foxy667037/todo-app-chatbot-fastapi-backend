import os
import subprocess
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values
import pytest
from httpx import ASGITransport, AsyncClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
project_environment = dotenv_values(".env")
configured_database_url = os.environ.get("DATABASE_URL") or project_environment.get(
    "DATABASE_URL"
)
configured_environment = (
    os.environ.get("ENVIRONMENT") or project_environment.get("ENVIRONMENT") or ""
)

if TEST_DATABASE_URL:
    if TEST_DATABASE_URL == configured_database_url:
        raise RuntimeError("TEST_DATABASE_URL must not equal DATABASE_URL")
    if configured_environment.lower() == "production":
        raise RuntimeError("Tests cannot run when ENVIRONMENT is production")
    if "test" not in (urlsplit(TEST_DATABASE_URL).path or "").lower():
        raise RuntimeError("TEST_DATABASE_URL database name must contain 'test'")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ["DATABASE_URL"] = (
        "postgresql+psycopg://todo_test:todo_test@localhost:5432/todo_test"
    )

os.environ["JWT_SECRET_KEY"] = "unit-test-only-secret-key-with-more-than-32-characters"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["ENVIRONMENT"] = "test"


@pytest.fixture(scope="session")
def migrated_test_database():
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL test database")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=os.environ.copy(),
    )
    yield


@pytest.fixture
async def empty_database(migrated_test_database):
    from app.db.session import AsyncSessionLocal
    from app.models.task import Task
    from app.models.user import User
    from sqlalchemy import delete

    async with AsyncSessionLocal() as session:
        await session.execute(delete(Task))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def client(migrated_test_database, empty_database):
    from app.api.v1.endpoints.auth import get_db
    from app.db.session import AsyncSessionLocal
    from app.main import app

    async def test_database_session():
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = test_database_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def register(client: AsyncClient, email: str, password: str = "TestPassword123!") -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Test Person", "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(client: AsyncClient, email: str, password: str = "TestPassword123!") -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
