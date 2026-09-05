from langfuse import Langfuse

from config.config import Config

# Single shared client for the whole app — every span/generation opened anywhere
# in the pipeline nests under whatever span is currently active (via OTEL context
# propagation, which also survives asyncio.to_thread hops), so this is the only
# Langfuse object the rest of the codebase needs.
langfuse_client = Langfuse(
    secret_key=Config.LANGFUSE_SECRET_KEY,
    public_key=Config.LANGFUSE_PUBLIC_KEY,
    host=Config.LANGFUSE_BASE_URL,
)
