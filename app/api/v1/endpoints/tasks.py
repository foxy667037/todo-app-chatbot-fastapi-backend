from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.core.permissions import require_active_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.task import TaskCreate, TaskUpdate, TaskOut, TaskList
from app.services.task_service import (
    create_task,
    delete_task,
    get_task_accessible,
    list_tasks,
    update_task,
)

router = APIRouter()


@router.get("", response_model=TaskList)
@router.get("/", response_model=TaskList)
async def list_tasks_endpoint(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=255),
    status: Literal["todo", "in_progress", "completed"] | None = Query(None),
    priority: Literal["low", "medium", "high"] | None = Query(None),
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
):
    return await list_tasks(
        session,
        current_user,
        page=page,
        size=size,
        search=search,
        status=status,
        priority=priority,
    )


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    task_in: TaskCreate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
):
    return await create_task(session, task_in, current_user)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_endpoint(
    task_id: int,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
):
    task = await get_task_accessible(session, task_id, current_user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task_endpoint(
    task_id: int,
    task_in: TaskUpdate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
):
    task = await get_task_accessible(session, task_id, current_user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return await update_task(session, task, task_in, current_user)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: int,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
):
    task = await get_task_accessible(session, task_id, current_user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await delete_task(session, task, current_user)