import time
import chromadb

from src.adapters.chroma_db import DEFAULT_PERSIST_DIR
from src.adapters.openrouter import openrouter
from src.adapters.logger import logger

SIMILARITY_DISTANCE_THRESHOLD = 0.28 # Very strict — only near-identical questions will match.
CACHE_TILL_SECONDS = 60 * 60 * 24 # 24hours

class ResponseCacheService:
    """
    Semantic cache for final answers — if a new question is close enough
    (by embedding similarity) to a previously answered one, we skip the
    entire pipeline (intent check, retrieval/SQL, generation) and return
    the cached answer directly.
    """
    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(name='response_cache')

    def get_cached_answer(self, question: str) -> str:
        """Returns a cached answer if a close-enough match exists and hasn't expired, else None."""
        if self._collection.count() == 0:
            return None

        query_embedding = openrouter.create_embedding(question)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=1
        )

        if not results['ids'][0]:
            return None

        distance = results['distances'][0][0]
        logger.info(f"DEBUG CACHE - question: '{question}' | closest distance: {distance}")
        if distance > SIMILARITY_DISTANCE_THRESHOLD:
            return None

        metadata = results['metadatas'][0][0]
        cached_at = metadata.get('cached_at', 0)
        if time.time() - cached_at > CACHE_TILL_SECONDS:
            return None # Expired

        return metadata.get('answer')

    def set_cached_answer(self, question: str, answer: str) -> None:
        """Stores a question-answer pair in the cache."""
        embedding = openrouter.create_embedding(question)
        entry_id = question[:200]

        self._collection.upsert(
            ids=[entry_id],
            documents=[question],
            embeddings=[embedding],
            metadatas=[{"question": question, "answer": answer, "cached_at": time.time()}],
        )

    def clear(self) -> None:
        """Wipes the entire cache — called when documents/tables change, since old answers may now be stale."""
        self._client.delete_collection(name="response_cache")
        self._collection = self._client.get_or_create_collection(name="response_cache")

response_cache = ResponseCacheService()
