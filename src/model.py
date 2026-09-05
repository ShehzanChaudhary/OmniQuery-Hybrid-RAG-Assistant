import json
import uuid
from pathlib import Path

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel


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
    def __init__(self, session_id: Optional[str] = None, history_turns: int = 3):
        self.history_turns = history_turns
        self.messages: list[Message] = []
        self.title: Optional[str] = None
        self.created_at: str = datetime.now().isoformat()

        if session_id:
            # Existing session - load from file
            self.session_id = session_id
            self._load()
        else:
            # Create new session
            self.session_id = str(uuid.uuid4())

    def _file_path(self) -> Path:
        return SESSIONS_DIR / f"{self.session_id}.json"

    def add(self, role: Role, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

        # The title will be set only the first time — the user's first message of the session.
        if self.title is None and role == 'user':
            self.title = content[:60]   # Truncate title, to see in the sidebar

        self._save()   # File will be updated after every new message

    def recent(self) -> list[Message]:
        return self.messages[-(self.history_turns * 2):]

    def _save(self) -> None:
        data = {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "messages": [m.to_dict() for m in self.messages],
        }
        with open(self._file_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        path = self._file_path()
        if not path.exists():
            # Given session_id but file not found, create new session
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.title = data.get("title")
        self.created_at = data.get("created_at", self.created_at)
        self.messages = [Message(role=m["role"], content=m["content"]) for m in data.get("messages", [])]

    @staticmethod
    def list_sessions() -> list[dict]:
        """
        Returns metadata for all saved sessions (for the sidebar) —
        session_id, title, created_at — without loading full message history.
        """
        sessions = []
        for file_path in SESSIONS_DIR.glob("*.json"):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "session_id": data.get("session_id"),
                "title": data.get("title") or "New Chat",
                "created_at": data.get("created_at"),
            })
        # Most recent session at the top
        sessions.sort(key=lambda s: s["created_at"], reverse=True)
        return sessions

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