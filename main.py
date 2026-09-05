import time
import json
import shutil
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from src.model import QueryRequest, Conversation
from src.utils import generate_final_response, generate_final_response_stream
from src.adapters.chroma_db import chroma_db
from src.adapters.schema_index import schema_index
from src.adapters.sqlite_db import sqlite_db
from src.ingestion import ingest_pdf, sanitize_document_id
from src.adapters.response_cache import response_cache
from src.adapters.tracing import langfuse_client


UPLOADS_DIR = Path(__file__).parent / 'data' / 'uploads'
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Langfuse batches spans in the background — flush on shutdown so a
    # container restart/redeploy doesn't drop whatever hasn't been exported yet.
    langfuse_client.flush()


app = FastAPI(title='RAG Pipeline', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/health')
def health():
    return {'status': 'RAG Pipeline is alive'}


@app.post('/query')
def query(request: QueryRequest):
    start_time = time.time()

    answer, tokens_used, session_id, followup_questions = generate_final_response(
        question=request.question,
        session_id=request.session_id,
    )
    time_taken = round(time.time() - start_time, 2)

    return {
        "answer": answer,
        "tokens_used": tokens_used,
        "time_taken": time_taken,
        "session_id": session_id,
        "followup_questions": followup_questions   #  Tells the frontend which session the conversation took place in.
    }


@app.post('/query/stream')
async def query_stream(request: QueryRequest):
    async def event_generator():
        start_time = time.time()
        session_id_from_stream = None
        followup_questions_from_stream = []

        async for chunk in generate_final_response_stream(
            question=request.question,
            session_id=request.session_id,
        ):
            # Distinguish the session ID marker from normal text chunks.
            if chunk.startswith("__SESSION_ID__:"):
                session_id_from_stream = chunk.split(":", 1)[1]
                continue   # This chunk should not appear as text to the user.

            if chunk.startswith("__FOLLOWUPS__:"):   
                followup_json = chunk.split(":", 1)[1]
                followup_questions_from_stream = json.loads(followup_json)
                continue

            payload = json.dumps({"chunk": chunk})
            yield f"data: {payload}\n\n"

        time_taken = round(time.time() - start_time, 2)
        done_payload = json.dumps({
            "done": True,
            "time_taken": time_taken,
            "session_id": session_id_from_stream, 
            "followup_questions": followup_questions_from_stream,
        })
        yield f"data: {done_payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get('/sessions')
def list_sessions():
    """
    Returns metadata for all saved chat sessions — used to populate the sidebar.
    Does NOT include full message history (keeps this endpoint fast).
    """
    return Conversation.list_sessions()


@app.get('/sessions/{session_id}')
def get_session(session_id: str):
    """
    Returns the full message history for one session — called when the user
    clicks a chat in the sidebar to load it.
    """
    conversation = Conversation(session_id=session_id)

    if not conversation.messages:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": conversation.session_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "messages": [m.to_dict() for m in conversation.messages],
    }


@app.get('/documents')
async def list_documents():
    """Returns one row per document stored in ChromaDB — used to populate the document manager UI."""
    return await chroma_db.alist_documents()


@app.post('/documents')
async def upload_document(file: UploadFile = File(...)):
    """Ingests an uploaded PDF: saves it, extracts + chunks + embeds the text, and stores it in ChromaDB."""
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    document_id = sanitize_document_id(file.filename)

    existing = await chroma_db.alist_documents()
    if any(doc["document_id"] == document_id for doc in existing):
        raise HTTPException(
            status_code=409,
            detail=f"A document named '{document_id}' already exists. Delete it first or rename the file.",
        )

    file_path = UPLOADS_DIR / f"{document_id}.pdf"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        chunk_count = await asyncio.to_thread(ingest_pdf, document_id, file.filename, file_path)
    except Exception as ex:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to ingest PDF: {ex}")

    await asyncio.to_thread(response_cache.clear)

    return {"document_id": document_id, "filename": file.filename, "chunk_count": chunk_count}


@app.delete('/documents/{document_id}')
async def delete_document(document_id: str):
    """Removes every chunk for this document from ChromaDB and deletes the stored PDF file."""
    deleted_count = await chroma_db.aremove_document_by_source(document_id)

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")

    (UPLOADS_DIR / f"{document_id}.pdf").unlink(missing_ok=True)

    await asyncio.to_thread(response_cache.clear)

    return {"document_id": document_id, "deleted_chunks": deleted_count}

@app.get('/tables')
def list_tables():
    """Returns all tables in SQLite along with their schema — populates the table manager UI."""
    tables = sqlite_db.list_tables()
    return [
        {
            'table_name': t,
            'columns': sqlite_db.get_schema(t),
            "row_count": sqlite_db.get_row_count(t)
        }
        for t in tables
    ]

@app.post('/tables')
async def upload_table(file: UploadFile = File(...)):
    """Ingests an uploaded Excel file: saves it, and loads it into SQLite as a new table."""
    if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only .xlsx or .xls files are supported")

    table_name = sanitize_document_id(Path(file.filename).stem)

    file_path = UPLOADS_DIR / file.filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = await asyncio.to_thread(sqlite_db.create_table_from_excel, str(file_path), table_name)
        await asyncio.to_thread(schema_index.index_table, result["table_name"], result["columns"])
    except Exception as ex:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to create table: {ex}")

    await asyncio.to_thread(response_cache.clear)

    return result   # { "table_name": ..., "columns": [...], "row_count": ... }

@app.delete('/tables/{table_name}')
async def delete_table(table_name: str):
    """Drops a table from SQLite."""
    await asyncio.to_thread(sqlite_db.remove_table, table_name=table_name)
    await asyncio.to_thread(schema_index.remove_table, table_name)
    await asyncio.to_thread(response_cache.clear)
    return {"status": "deleted", "table_name": table_name}


# Serves the frontend (index.html/script.js/style.css) from the same origin as the
# API. Mounted last so it never shadows the API routes above — Starlette matches
# routes in registration order, and this is a catch-all on "/".
FRONTEND_DIR = Path(__file__).parent / 'frontend'
app.mount('/', StaticFiles(directory=FRONTEND_DIR, html=True), name='frontend')