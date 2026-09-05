import os
import chromadb

from src.adapters.openrouter import openrouter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_store")

# If the column count exceeds the limit, we will perform column-level retrieval; otherwise,
# we will simply provide the schema for the entire table (extra retrieval is unnecessary for small tables).
WIDE_TABLE_COLUMN_THRESHOLD = 30


class SchemaIndexService:
    """
    Vector index over table/column metadata (not the actual row data).
    Lets us find the handful of tables/columns relevant to a question,
    instead of stuffing every table's full schema into the prompt.
    """

    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._tables_collection = self._client.get_or_create_collection(name="table_schemas")
        self._columns_collection = self._client.get_or_create_collection(name="table_columns")

    def index_table(self, table_name: str, columns: list[dict]) -> None:
        """
        Called whenever a table is created/re-uploaded. Indexes:
        1. One entry describing the whole table (for table-level retrieval)
        2. One entry per column (for column-level retrieval, used only when the table is wide)
        """
        column_names = [c["name"] for c in columns]

        # --- Table-level entry ---
        table_description = f"Table: {table_name}. Columns: {', '.join(column_names)}."
        table_embedding = openrouter.create_embedding(table_description)

        self._tables_collection.upsert(
            ids=[table_name],
            documents=[table_description],
            embeddings=[table_embedding],
            metadatas=[{"table_name": table_name, "column_count": len(columns)}],
        )

        # --- Column-level entries (only useful for wide tables, but we always index for simplicity) ---
        # Do delete old column entries from the table (if re-uploaded then columns can be changed)
        self.remove_table(table_name, remove_table_entry=False)

        column_ids = [f"{table_name}::{c['name']}" for c in columns]
        column_texts = [f"Column '{c['name']}' (type: {c['type']}) in table '{table_name}'." for c in columns]
        column_embeddings = [openrouter.create_embedding(t) for t in column_texts]
        column_metadatas = [{"table_name": table_name, "column_name": c["name"]} for c in columns]

        self._columns_collection.upsert(
            ids=column_ids,
            documents=column_texts,
            embeddings=column_embeddings,
            metadatas=column_metadatas,
        )

    def remove_table(self, table_name: str, remove_table_entry: bool = True) -> None:
        """Removes a table's entries from both collections (used on delete, and before re-indexing)."""
        if remove_table_entry:
            self._tables_collection.delete(ids=[table_name])

        existing = self._columns_collection.get(where={"table_name": table_name})
        if existing["ids"]:
            self._columns_collection.delete(ids=existing["ids"])

    def get_relevant_tables(self, question: str, top_k: int = 5) -> list[str]:
        """Returns the names of the top_k tables most relevant to the question."""
        if self._tables_collection.count() == 0:
            return []

        query_embedding = openrouter.create_embedding(question)
        results = self._tables_collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._tables_collection.count()),
        )
        return [meta["table_name"] for meta in results["metadatas"][0]]

    def get_relevant_columns(self, question: str, table_name: str, top_k: int = 20) -> list[str]:
        """Returns the names of the top_k columns (within one table) most relevant to the question."""
        results = self._columns_collection.get(where={"table_name": table_name})
        if not results["ids"]:
            return []

        # No need for retrieval for small tables — just return all columns.
        if len(results["ids"]) <= WIDE_TABLE_COLUMN_THRESHOLD:
            return [meta["column_name"] for meta in results["metadatas"]]

        query_embedding = openrouter.create_embedding(question)
        query_results = self._columns_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"table_name": table_name},
        )
        return [meta["column_name"] for meta in query_results["metadatas"][0]]


schema_index = SchemaIndexService()