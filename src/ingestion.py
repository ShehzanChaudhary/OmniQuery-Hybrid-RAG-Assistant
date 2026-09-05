import re
from pathlib import Path

from pypdf import PdfReader

from src.model import Chunk
from src.adapters.chroma_db import chroma_db


def sanitize_document_id(filename: str) -> str:
    """Turns a filename into a safe, stable document id (also used as the chunk-id prefix)."""
    stem = Path(filename).stem
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_")
    return slug or "document"


def extract_pdf_pages(file_path: Path) -> list[str]:
    """Returns one text string per PDF page, in page order, skipping pages with no extractable text."""
    reader = PdfReader(str(file_path))
    pages = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)
    return pages


def build_chunks(document_id: str, filename: str, pages: list[str]) -> list[Chunk]:
    """One chunk per PDF page (page-wise chunking)."""
    return [
        Chunk(
            id=f"{document_id}_page_{page_number}",
            text=page_text,
            metadata={"source": document_id, "filename": filename, "page": page_number},
        )
        for page_number, page_text in enumerate(pages, start=1)
    ]


def ingest_pdf(document_id: str, filename: str, file_path: Path) -> int:
    """
    Extracts, chunks (one chunk per page), embeds, and stores a PDF's text in ChromaDB.
    Sync + potentially slow (PDF parsing + one embedding call per chunk) —
    callers on the async path should run this via asyncio.to_thread.
    Returns the number of chunks stored.
    """
    pages = extract_pdf_pages(file_path)
    chunks = build_chunks(document_id, filename, pages)

    if not chunks:
        raise ValueError("No extractable text found in PDF")

    chroma_db.add_document(chunks)
    return len(chunks)
