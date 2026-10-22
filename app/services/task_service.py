from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskUpdate, TaskOut, TaskList


async def create_task(
    session: AsyncSession, task_in: TaskCreate, current_user: User
) -> Task:
    task = Task(**task_in.model_dump(), owner_id=current_user.id)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def get_task_accessible(
    session: AsyncSession, task_id: int, current_user: User
) -> Task | None:
    query = select(Task).where(Task.id == task_id)
    if current_user.role != "admin":
        query = query.where(Task.owner_id == current_user.id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_tasks(
    session: AsyncSession,
    current_user: User,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> TaskList:
    query = select(Task)
    count_query = select(func.count()).select_from(Task)

    if current_user.role != "admin":
        query = query.where(Task.owner_id == current_user.id)
        count_query = count_query.where(Task.owner_id == current_user.id)

    if search:
        escaped_search = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        cond = or_(
            Task.title.ilike(pattern, escape="\\"),
            Task.description.ilike(pattern, escape="\\"),
        )
        query = query.where(cond)
        count_query = count_query.where(cond)

    if status:
        query = query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)

    if priority:
        query = query.where(Task.priority == priority)
        count_query = count_query.where(Task.priority == priority)

    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    offset = (page - 1) * size
    query = query.offset(offset).limit(size).order_by(Task.created_at.desc())
    result = await session.execute(query)
    items = result.scalars().all()

    pages = (total + size - 1) // size if total else 0
    return TaskList(
        items=[TaskOut.model_validate(i) for i in items],
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


async def update_task(
    session: AsyncSession,
    task: Task,
    task_in: TaskUpdate,
    current_user: User,
) -> Task:
    if current_user.role != "admin" and task.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    data = task_in.model_dump(exclude_unset=True)

    for field, value in data.items():
        setattr(task, field, value)

    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(
    session: AsyncSession, task: Task, current_user: User
) -> None:
    if current_user.role != "admin" and task.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await session.delete(task)
    await session.commit()