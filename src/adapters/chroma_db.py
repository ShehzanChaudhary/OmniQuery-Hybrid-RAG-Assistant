import os
import chromadb
import asyncio

from src.model import Chunk, RetrievedChunk
from src.adapters.openrouter import openrouter

# Determine and fix the absolute path of the project root (three levels up
# from src/adapters/chroma_db.py: adapters -> src -> project root).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_store")


class ChromaDBService:
    def __init__(self,  collection_name: str = "rag_documents", persist_dir: str = DEFAULT_PERSIST_DIR):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(name=collection_name)

    def add_document(self, chunks: list[Chunk]) -> None:
        ids = [c.id for c in chunks]
        texts = [c.text for c in chunks]
        metadatas = [c.metadata for c in chunks]
        embeddings = [openrouter.create_embedding(t) for t in texts]

        self._collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def remove_document(self, ids: list[str]) -> None:
        self._collection.delete(ids=ids)

    def remove_document_by_source(self, source: str) -> int:
        """Deletes every chunk belonging to the given document (metadata `source`). Returns the number of chunks deleted."""
        existing = self._collection.get(where={"source": source}, include=[])
        count = len(existing["ids"])
        if count:
            self._collection.delete(where={"source": source})
        return count

    def list_documents(self) -> list[dict]:
        """
        Groups all stored chunks by their `source` document, for the UI's
        document list — one row per uploaded document, not one per chunk.
        """
        results = self._collection.get(include=["metadatas"])

        documents: dict[str, dict] = {}
        for metadata in results["metadatas"]:
            source = metadata.get("source", "unknown")
            doc = documents.setdefault(source, {
                "document_id": source,
                "filename": metadata.get("filename", source),
                "chunk_count": 0,
            })
            doc["chunk_count"] += 1

        return sorted(documents.values(), key=lambda d: d["filename"])

    def fetch_chunks(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        query_embedding = openrouter.create_embedding(query)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        retrieved = []
        for i in range(len(results["ids"][0])):
            retrieved.append(RetrievedChunk(
                id=results["ids"][0][i],
                text=results["documents"][0][i],
                metadata=results["metadatas"][0][i],
                distance=results["distances"][0][i],
            ))
        return retrieved

    async def afetch_chunks(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
         """
        Async wrapper around fetch_chunks(). ChromaDB itself is sync, so this
        runs the existing sync method in a background thread (asyncio.to_thread)
        instead of blocking the event loop.
        """
         return await asyncio.to_thread(self.fetch_chunks, query, top_k)

    async def aadd_document(self, chunks: list[Chunk]) -> None:
        await asyncio.to_thread(self.add_document, chunks)

    async def alist_documents(self) -> list[dict]:
        return await asyncio.to_thread(self.list_documents)

    async def aremove_document_by_source(self, source: str) -> int:
        return await asyncio.to_thread(self.remove_document_by_source, source)


chroma_db = ChromaDBService(collection_name="attention_paper")
