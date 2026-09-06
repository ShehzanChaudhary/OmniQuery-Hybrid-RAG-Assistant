import json
import uuid
from pathlib import Path

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel
from sqlalchemy import text
from src.adapters.mysql_db import SessionLocal


Role = Literal['system', 'user', 'assistant']

# Each session file will be save on this path
SESSIONS_DIR = Path(__file__).parent.parent / 'data' / 'sessions'
SESSIONS_DIR.mkdir(parents=True, exist_ok=True) # Creat if not exists

@dataclass
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class Conversation:
    def __init__(self, user_id: int, session_id: Optional[str] = None, history_turns: int = 3):
        self.user_id = user_id
        self.history_turns = history_turns
        self.messages: list[Message] = []
        self.title: Optional[str] = None
        self.created_at: str = datetime.now().isoformat()

        if session_id:
            self.session_id = session_id
            self._load()
        else:
            self.session_id = str(uuid.uuid4())
            self._create_session_row()

    def _create_session_row(self) -> None:
        """Inserts a new row into the sessions table for a brand-new conversation."""
        db = SessionLocal()
        try:
            db.execute(
                text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :user_id, :title)"),
                {"id": self.session_id, "user_id": self.user_id, "title": None},
            )
            db.commit()
        finally:
            db.close()

    def _load(self) -> None:
        """Loads an existing session's messages from MySQL — only if it belongs to this user."""
        db = SessionLocal()
        try:
            session_row = db.execute(
                text("SELECT title, created_at FROM sessions WHERE id = :id AND user_id = :user_id"),
                {"id": self.session_id, "user_id": self.user_id},
            ).fetchone()

            if session_row is None:
                # Either the session doesn't exist, or it belongs to a different user —
                # treat it as a fresh session rather than leaking someone else's data.
                self._create_session_row()
                return

            self.title, created_at = session_row
            self.created_at = created_at.isoformat() if created_at else self.created_at

            rows = db.execute(
                text("SELECT role, content FROM messages WHERE session_id = :id ORDER BY id ASC"),
                {"id": self.session_id},
            ).fetchall()

            self.messages = [Message(role=row[0], content=row[1]) for row in rows]
        finally:
            db.close()

    def add(self, role: Role, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

        db = SessionLocal()
        try:
            if self.title is None and role == 'user':
                self.title = content[:60]
                db.execute(
                    text("UPDATE sessions SET title = :title WHERE id = :id"),
                    {"title": self.title, "id": self.session_id},
                )

            db.execute(
                text("INSERT INTO messages (session_id, role, content) VALUES (:session_id, :role, :content)"),
                {"session_id": self.session_id, "role": role, "content": content},
            )
            db.commit()
        finally:
            db.close()

    def recent(self) -> list[Message]:
        return self.messages[-(self.history_turns * 2):]

    @staticmethod
    def list_sessions(user_id: int) -> list[dict]:
        """Returns metadata for all sessions belonging to this user (for the sidebar)."""
        db = SessionLocal()
        try:
            rows = db.execute(
                text("SELECT id, title, created_at FROM sessions WHERE user_id = :user_id ORDER BY created_at DESC"),
                {"user_id": user_id},
            ).fetchall()

            return [
                {
                    "session_id": row[0],
                    "title": row[1] or "New Chat",
                    "created_at": row[2].isoformat() if row[2] else None,
                }
                for row in rows
            ]
        finally:
            db.close()

@dataclass
class Chunk:
    """A single chunk of a document, to be stored in ChromaDB at the time of ingestion."""
    id: str
    text: str
    metadata: dict = field(default_factory=dict)

@dataclass
class RetrievedChunk:
    """Chunk returned after the query from Charomdab, along with the similarity score."""
    id: str
    text: str
    metadata: dict
    distance: float

@dataclass
class QueryResponse:
    """The final response sent to the frontend will include the answer plus extra stats."""
    answer: str
    tokens_used: Optional[int] = None
    time_taken: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'answer': self.answer,
            'tokens_used': self.tokens_used,
            'time_taken': self.time_taken
        }



class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

