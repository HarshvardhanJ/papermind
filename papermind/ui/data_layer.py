"""Chainlit persistence adapter backed by PaperMind's existing chat database."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from chainlit.data.base import BaseDataLayer
from chainlit.types import PageInfo, PaginatedResponse, Pagination, ThreadFilter
from chainlit.user import PersistedUser, User

from papermind.ui.chat_db import ChatMessage, ChatSession, ChatSessionLocal
from papermind.ui.components.citations import append_citation_tooltips


def _iso(value: Optional[datetime]) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _thread_title(session: ChatSession) -> str:
    title = (session.title or "").strip()
    if title and title.lower() not in {"new chat", "untitled chat"}:
        return title
    for message in session.messages:
        if message.role == "user" and message.content.strip():
            return message.content.strip().splitlines()[0][:72]
    if session.files:
        return session.files[0].filename
    return "New chat"


class ChatHistoryDataLayer(BaseDataLayer):
    """Expose stored PaperMind conversations in Chainlit's native history UI."""

    async def get_user(self, identifier: str) -> Optional[PersistedUser]:
        return PersistedUser(
            id=identifier,
            identifier=identifier,
            createdAt="1970-01-01T00:00:00+00:00",
        )

    async def create_user(self, user: User) -> Optional[PersistedUser]:
        # Claim pre-sidebar sessions created by PaperMind's older chat UI.
        with ChatSessionLocal() as db:
            db.query(ChatSession).filter(ChatSession.owner_id.is_(None)).update(
                {ChatSession.owner_id: user.identifier}, synchronize_session=False
            )
            db.commit()
        return PersistedUser(
            id=user.identifier,
            identifier=user.identifier,
            createdAt=datetime.now(timezone.utc).isoformat(),
            metadata=user.metadata or {},
        )

    async def get_thread_author(self, thread_id: str) -> str:
        with ChatSessionLocal() as db:
            session = db.query(ChatSession).filter(ChatSession.id == thread_id).first()
            return session.owner_id if session and session.owner_id else ""

    async def get_thread(self, thread_id: str):
        with ChatSessionLocal() as db:
            session = db.query(ChatSession).filter(ChatSession.id == thread_id).first()
            if not session:
                return None
            messages = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == thread_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
                .all()
            )
            steps = [
                {
                    "id": message.id,
                    "threadId": thread_id,
                    "parentId": None,
                    "name": "You" if message.role == "user" else "PaperMind",
                    "type": "user_message" if message.role == "user" else "assistant_message",
                    "input": "",
                    "output": (
                        append_citation_tooltips(message.content, message.citations or [])
                        if message.role == "assistant" and message.citations
                        and "**Sources:**" not in message.content
                        else message.content
                    ),
                    "createdAt": _iso(message.created_at),
                    "start": _iso(message.created_at),
                    "end": _iso(message.created_at),
                    "streaming": False,
                    "isError": False,
                    "metadata": {},
                    "tags": [],
                }
                for message in messages
            ]
            return {
                "id": session.id,
                "createdAt": _iso(session.created_at),
                "name": _thread_title(session),
                "userId": session.owner_id,
                "userIdentifier": session.owner_id,
                "tags": [],
                "metadata": {},
                "steps": steps,
                "elements": [],
            }

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse:
        if not filters.userId:
            return PaginatedResponse(
                pageInfo=PageInfo(hasNextPage=False, startCursor=None, endCursor=None),
                data=[],
            )
        with ChatSessionLocal() as db:
            sessions = (
                db.query(ChatSession)
                .filter(
                    ChatSession.owner_id == filters.userId,
                    ChatSession.messages.any() | ChatSession.files.any(),
                )
                .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
                .all()
            )
            rows = []
            for session in sessions:
                messages = sorted(session.messages, key=lambda item: (item.created_at, item.id))
                title = _thread_title(session)
                if filters.search:
                    query = filters.search.casefold()
                    if query not in title.casefold() and not any(
                        query in message.content.casefold() for message in messages
                    ):
                        continue
                rows.append((session.id, title, session.owner_id, session.created_at))

        start = 0
        if pagination.cursor:
            for index, row in enumerate(rows):
                if row[0] == pagination.cursor:
                    start = index + 1
                    break
        end = start + pagination.first
        page = rows[start:end]
        data = [
            {
                "id": thread_id,
                "createdAt": _iso(created_at),
                "name": title,
                "userId": owner_id,
                "userIdentifier": owner_id,
                "tags": [],
                "metadata": {},
                "steps": (await self.get_thread(thread_id))["steps"],
                "elements": [],
            }
            for thread_id, title, owner_id, created_at in page
        ]
        return PaginatedResponse(
            pageInfo=PageInfo(
                hasNextPage=len(rows) > end,
                startCursor=page[0][0] if page else None,
                endCursor=page[-1][0] if page else None,
            ),
            data=data,
        )

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ):
        with ChatSessionLocal() as db:
            session = db.query(ChatSession).filter(ChatSession.id == thread_id).first()
            if session:
                if name:
                    session.title = name[:120]
                if user_id:
                    session.owner_id = user_id
                session.updated_at = datetime.now(timezone.utc)
                db.commit()

    async def create_step(self, step_dict):
        # User and final assistant turns are saved with their citation data by the app.
        return None

    async def update_step(self, step_dict):
        return None

    async def delete_step(self, step_id: str):
        with ChatSessionLocal() as db:
            message = db.query(ChatMessage).filter(ChatMessage.id == step_id).first()
            if message:
                db.delete(message)
                db.commit()

    async def delete_thread(self, thread_id: str):
        with ChatSessionLocal() as db:
            session = db.query(ChatSession).filter(ChatSession.id == thread_id).first()
            if session:
                db.delete(session)
                db.commit()

    async def create_element(self, element):
        return None

    async def get_element(self, thread_id: str, element_id: str):
        return None

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None):
        return None

    async def upsert_feedback(self, feedback) -> str:
        return feedback.id or str(uuid.uuid4())

    async def delete_feedback(self, feedback_id: str) -> bool:
        return True

    async def get_favorite_steps(self, user_id: str):
        return []

    async def build_debug_url(self) -> str:
        return ""

    async def close(self):
        return None
