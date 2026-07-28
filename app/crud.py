"""Database access helpers.

`similarity_search` is deliberately absent: vector search now lives in
`app/services/vectors.py`, where `owner_id` is a required argument. The old
version here filtered only when `document_ids` was passed, which leaked every
user's chunk text on the default query path.
"""

import uuid
from typing import Any

from sqlmodel import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models import (
    Document,
    DocumentChunk,
    User,
    UserCreate,
    UserUpdate,
    UserUpdateMe,
)


# ──────────────────────────── User ────────────────────────────

async def create_user(*, session: AsyncSession, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create,
        update={"hashed_password": get_password_hash(user_create.password)},
    )
    session.add(db_obj)
    await session.commit()
    await session.refresh(db_obj)
    return db_obj


async def update_user(
    *, session: AsyncSession, db_user: User, user_in: UserUpdate | UserUpdateMe
) -> User:
    user_data = user_in.model_dump(exclude_unset=True, exclude_none=True)
    extra_data: dict[str, Any] = {}
    if "password" in user_data:
        extra_data["hashed_password"] = get_password_hash(user_data.pop("password"))
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def get_user(*, session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(*, session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def get_users(
    *, session: AsyncSession, skip: int = 0, limit: int = 100
) -> tuple[list[User], int]:
    count = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    result = await session.execute(select(User).offset(skip).limit(limit))
    return list(result.scalars().all()), int(count)


async def delete_user(*, session: AsyncSession, db_user: User) -> None:
    await session.delete(db_user)
    await session.commit()


async def authenticate(
    *, session: AsyncSession, email: str, password: str
) -> User | None:
    db_user = await get_user_by_email(session=session, email=email)
    if db_user is None or not verify_password(password, db_user.hashed_password):
        return None
    return db_user


# ──────────────────────────── Document ────────────────────────────

async def create_document(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    title: str,
    description: str | None,
    file_type: str | None,
) -> Document:
    db_doc = Document(
        owner_id=owner_id,
        title=title,
        description=description,
        file_type=file_type,
        status="pending",
    )
    session.add(db_doc)
    await session.commit()
    await session.refresh(db_doc)
    return db_doc


async def get_documents(
    *, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> tuple[list[Document], int]:
    count = (
        await session.execute(
            select(func.count()).select_from(Document).where(
                Document.owner_id == owner_id
            )
        )
    ).scalar_one()
    result = await session.execute(
        select(Document)
        .where(Document.owner_id == owner_id)
        .order_by(Document.created_at.desc())  # pyright: ignore[reportAttributeAccessIssue]
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), int(count)


async def get_document(
    *, session: AsyncSession, doc_id: uuid.UUID
) -> Document | None:
    return await session.get(Document, doc_id)


async def get_documents_by_ids(
    *, session: AsyncSession, doc_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Document]:
    """Batch fetch. Replaces the per-chunk N+1 lookup in the old query route."""
    if not doc_ids:
        return {}
    result = await session.execute(
        select(Document).where(Document.id.in_(doc_ids))  # pyright: ignore[reportAttributeAccessIssue]
    )
    return {doc.id: doc for doc in result.scalars().all()}


async def delete_document(*, session: AsyncSession, db_doc: Document) -> None:
    """Delete a document, its chunks, and its vectors.

    SQLite foreign keys do not cascade into the vec0 virtual table, so the
    vectors must be removed explicitly.
    """
    from app.services import vectors

    await vectors.delete_document(session, db_doc.id)
    await session.delete(db_doc)
    await session.commit()


# ──────────────────────────── Chunks ────────────────────────────

async def replace_chunks(
    *, session: AsyncSession, document_id: uuid.UUID, chunks: list[DocumentChunk]
) -> list[DocumentChunk]:
    """Replace a document's chunk rows. Idempotent across re-ingestion."""
    existing = await session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    for chunk in existing.scalars().all():
        await session.delete(chunk)
    for chunk in chunks:
        session.add(chunk)
    await session.commit()
    return chunks


async def get_chunks_by_ids(
    *, session: AsyncSession, chunk_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DocumentChunk]:
    if not chunk_ids:
        return {}
    result = await session.execute(
        select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))  # pyright: ignore[reportAttributeAccessIssue]
    )
    return {chunk.id: chunk for chunk in result.scalars().all()}
