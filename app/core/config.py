from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = Field(default="development")
    cors_origins: str = Field(default="http://localhost:5173")

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30, gt=0, le=1440)

    db_pool_size: int = Field(default=3, ge=1, le=20)
    db_max_overflow: int = Field(default=2, ge=0, le=20)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    db_pool_recycle_seconds: int = Field(default=300, ge=60, le=3600)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)

    admin_name: str | None = None
    admin_email: str | None = None
    admin_password: str | None = None

    openrouter_api_key: str = ""
    openrouter_model: str = Field(default="openrouter/auto")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("postgres://"):
            value = "postgresql://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value.removeprefix(
                "postgresql://"
            )
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError(
                "DATABASE_URL must use PostgreSQL with the psycopg driver"
            )
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def require_secure_jwt_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def require_hmac_jwt_algorithm(cls, value: str) -> str:
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be HS256, HS384, or HS512")
        return value

    @field_validator("cors_origins")
    @classmethod
    def require_explicit_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins or "*" in origins:
            raise ValueError("CORS_ORIGINS must contain explicit origins, not '*'")
        return ",".join(origins)

    @model_validator(mode="after")
    def require_secure_production_settings(self) -> "Settings":
        if self.environment.lower() == "production":
            sslmode = parse_qs(urlsplit(self.database_url).query).get(
                "sslmode", [""]
            )[0].lower()
            if sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError(
                    "Production DATABASE_URL must enable TLS with sslmode=require "
                    "or stronger"
                )
            origins = [origin.strip() for origin in self.cors_origins.split(",")]
            if any(urlsplit(origin).scheme != "https" for origin in origins):
                raise ValueError(
                    "Production CORS_ORIGINS must contain HTTPS origins"
                )
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()