import asyncio
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.security import get_password_hash
from app.models.user import User


def required_admin_configuration() -> tuple[str, str, str]:
    settings = get_settings()
    name = (settings.admin_name or "").strip()
    email = (settings.admin_email or "").strip().lower()
    password = settings.admin_password or ""
    if not name or len(name) > 255:
        raise ValueError("ADMIN_NAME must be between 1 and 255 characters")
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email))
    except ValidationError as exc:
        raise ValueError("ADMIN_EMAIL must be a valid email address") from exc
    if len(password) < 12 or len(password) > 128:
        raise ValueError("ADMIN_PASSWORD must be between 12 and 128 characters")
    return name, email, password


async def seed_admin() -> bool:
    name, email, password = required_admin_configuration()
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(select(User).where(User.email == email))
            existing = result.scalar_one_or_none()
            if existing:
                if existing.role != "admin":
                    raise ValueError(
                        "The configured email belongs to a non-admin account; "
                        "no account changes were made"
                    )
                print("Configured admin already exists; no account changes were made.")
                return False
            session.add(
                User(
                    full_name=name,
                    email=email,
                    password_hash=get_password_hash(password),
                    role="admin",
                    is_active=True,
                )
            )
            await session.commit()
            print("Admin account created.")
            return True
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(seed_admin())
    except (ValueError, OSError) as exc:
        print(f"Admin seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
