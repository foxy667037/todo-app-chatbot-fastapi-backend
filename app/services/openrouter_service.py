import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class OpenRouterService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = base_url or settings.openrouter_base_url
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self.api_key:
                raise OpenRouterError("OpenRouter is not configured", status_code=503)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "required"

        try:
            resp = await self.client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise OpenRouterError("OpenRouter returned an invalid response")
            return data
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            logger.warning("OpenRouter request failed with status %s", code)
            raise OpenRouterError(
                f"OpenRouter request failed with status {code}",
                status_code=503 if code == 429 or code >= 500 else 502,
            ) from exc
        except httpx.RequestError as exc:
            logger.warning("OpenRouter request could not be completed: %s", type(exc).__name__)
            raise OpenRouterError("OpenRouter request could not be completed", 503) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("OpenRouter returned malformed JSON")
            raise OpenRouterError("OpenRouter returned an invalid response") from exc

    @staticmethod
    def extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            message = response["choices"][0]["message"]
            calls = message.get("tool_calls", [])
            if not isinstance(calls, list):
                raise ValueError("tool_calls is not a list")
            return calls
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise OpenRouterError("OpenRouter returned an invalid response") from exc