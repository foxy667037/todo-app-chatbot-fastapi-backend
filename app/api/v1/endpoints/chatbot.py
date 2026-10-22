import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.permissions import require_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.chatbot import ChatbotMessage, ChatbotResponse
from app.services.chatbot_service import ChatbotService
from app.services.openrouter_service import OpenRouterError, OpenRouterService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/message", response_model=ChatbotResponse)
async def chatbot_message(
    message_in: ChatbotMessage,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
):
    openrouter = OpenRouterService()
    try:
        service = ChatbotService(session, current_user, openrouter)
        result = await service.handle_message(message_in.message)
        return ChatbotResponse(**result)
    except OpenRouterError as exc:
        logger.warning("Chatbot provider request failed: %s", exc)
        raise HTTPException(
            status_code=exc.status_code,
            detail="The chatbot service could not complete the request.",
        ) from exc
    finally:
        await openrouter.close()