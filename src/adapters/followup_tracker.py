import chromadb
from collections import Counter

from src.adapters.chroma_db import DEFAULT_PERSIST_DIR
from src.adapters.openrouter import openrouter

MIN_OCCURRENCES = 3   # Trust this pattern only if it has been observed at least this many times.
SIMILARITY_DISTANCE_THRESHOLD = 0.15   # How "close" a match do you want? (Smaller = stricter)


class FollowupTrackerService:
    """
    Tracks which question naturally follows another (based on real usage),
    so popular follow-up suggestions can be served without an LLM call.
    Falls back to LLM generation for new/rare questions.
    """

    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(name="question_transitions")

    def record_transition(self, question: str, next_question: str) -> None:
        """Called when we know a user asked `next_question` right after `question`."""
        embedding = openrouter.create_embedding(question)
        entry_id = f"{question}::{next_question}"[:200]   # simple unique-ish id

        self._collection.upsert(
            ids=[entry_id],
            documents=[question],
            embeddings=[embedding],
            metadatas=[{"question": question, "next_question": next_question}],
        )

    def get_popular_followups(self, question: str, top_k: int = 15) -> list[str]:
        """
        Looks for similar past questions and returns the most common things
        asked right after them — only if there's enough historical signal.
        Returns an empty list if nothing qualifies (caller should fall back to LLM).
        """
        if self._collection.count() == 0:
            return []

        query_embedding = openrouter.create_embedding(question)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
        )

        if not results["ids"][0]:
            return []

        # Keep close-enough matches only
        candidates = []
        for metadata, distance in zip(results["metadatas"][0], results["distances"][0]):
            if distance <= SIMILARITY_DISTANCE_THRESHOLD:
                candidates.append(metadata["next_question"])

        if not candidates:
            return []

        # Find the most common next-questions
        counts = Counter(candidates)
        top_questions = [q for q, count in counts.most_common(3) if count >= MIN_OCCURRENCES]

        return top_questions


followup_tracker = FollowupTrackerService()