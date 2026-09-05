FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# chromadb's dependencies (chroma-hnswlib, onnxruntime, tokenizers) ship prebuilt
# wheels for linux/amd64 + this Python version, so no compiler toolchain is
# needed. If a future dependency bump breaks that, uncomment:
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

# Frontend + backend are served by the same FastAPI process on this one port —
# see the StaticFiles mount at the bottom of main.py.
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
