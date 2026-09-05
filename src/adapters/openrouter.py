import logging
import random
import time

from openai import OpenAI, AsyncOpenAI
from typing import AsyncGenerator

from config.config import Config
from src.model import Message
from src.adapters.tracing import langfuse_client

logger = logging.getLogger(__name__)


class OpenRouterService:
    """
    Helper class for interacting with OpenRouter (OpenAI-compatible API) for
    chat completions and embedding generation, with retry/backoff handling.
    """

    def __init__(self):
        self._client = OpenAI(api_key=Config.OPENROUTER_API_KEY, base_url=Config.OPENAI_BASE_URL)
        self._async_client = AsyncOpenAI(api_key=Config.OPENROUTER_API_KEY, base_url=Config.OPENAI_BASE_URL)
        self._model = Config.MODEL
        self._embed_model = Config.EMBED_MODEL
        logger.info("STATUS: OpenRouter client created successfully!")

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """Exponential backoff delay with jitter for retry attempts."""
        return (2 ** attempt) + random.uniform(0, 1)

    @staticmethod
    def _usage_details(usage) -> dict:
        return {
            "input": usage.prompt_tokens,
            "output": usage.completion_tokens,
            "total": usage.total_tokens,
        }

    def chat(self, messages: list[Message], json_mode: bool = False, max_retries: int = 2, name: str = "chat") -> tuple[str, int]:
        message_dicts = [m.to_dict() for m in messages]

        with langfuse_client.start_as_current_observation(
            name=name,
            as_type="generation",
            input=message_dicts,
            model=self._model,
            model_parameters={"temperature": 0, "json_mode": json_mode},
        ) as gen:
            for attempt in range(max_retries):
                try:
                    response = self._client.chat.completions.create(
                        model=self._model,
                        messages=message_dicts,
                        temperature=0,
                        **({"response_format": {"type": "json_object"}} if json_mode else {}),
                    )
                    content = response.choices[0].message.content
                    gen.update(output=content, usage_details=self._usage_details(response.usage))
                    return content, response.usage.total_tokens
                except Exception as ex:
                    logger.error(f"OpenRouter chat request failed on attempt {attempt + 1}: {ex}", exc_info=True)
                    if attempt < max_retries - 1:
                        time.sleep(self._backoff_delay(attempt))

            fallback = "Sorry, I'm having trouble responding right now. Please try again."
            gen.update(output=fallback, level="ERROR", status_message="All retries failed")
            return fallback, 0

    async def achat(self, messages: list[Message], json_mode: bool = False, max_retries: int = 2, name: str = "achat") -> tuple[str, int]:
        """
        Async version of chat() — non-streaming. Use this when you need the
        full response but don't want to block the event loop while waiting
        (e.g. intent_check, rephrase_query — fast calls which does not stream).
        """
        message_dicts = [m.to_dict() for m in messages]

        with langfuse_client.start_as_current_observation(
            name=name,
            as_type="generation",
            input=message_dicts,
            model=self._model,
            model_parameters={"temperature": 0, "json_mode": json_mode},
        ) as gen:
            for attempt in range(max_retries):
                try:
                    response = await self._async_client.chat.completions.create(
                        model=self._model,
                        messages=message_dicts,
                        temperature=0,
                        **({'response_format': {'type': 'json_object'}} if json_mode else {}),
                    )
                    content = response.choices[0].message.content
                    gen.update(output=content, usage_details=self._usage_details(response.usage))
                    return content, response.usage.total_tokens
                except Exception as ex:
                    logger.error(f"OpenRouter async chat request failed on attempt {attempt + 1}: {ex}", exc_info=True)
                    if attempt < max_retries - 1:
                        time.sleep(self._backoff_delay(attempt))

            fallback = "Sorry, I'm having trouble responding right now. Please try again."
            gen.update(output=fallback, level="ERROR", status_message="All retries failed")
            return fallback, 0

    async def stream_chat(self, messages: list[Message], name: str = "stream_chat") -> AsyncGenerator[str, None]:
        """
        Streams the response token-by-token as it's generated. Use this ONLY
        for the final user-facing answer — not for intent_check/rephrase,
        since those are background steps the user never sees directly.

        Yields plain text chunks (str). Caller loops with `async for`.
        """
        message_dicts = [m.to_dict() for m in messages]

        with langfuse_client.start_as_current_observation(
            name=name,
            as_type="generation",
            input=message_dicts,
            model=self._model,
            model_parameters={"temperature": 0, "stream": True},
        ) as gen:
            full_text_parts = []
            try:
                stream = await self._async_client.chat.completions.create(
                    model=self._model,
                    messages=message_dicts,
                    temperature=0,
                    stream=True
                )

                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        full_text_parts.append(delta)
                        yield delta
            finally:
                gen.update(output="".join(full_text_parts))

    def create_embedding(self, text: str, max_retries: int = 2) -> list[float]:
        for attempt in range(max_retries):
            try:
                response = self._client.embeddings.create(model=self._embed_model, input=text)
                return response.data[0].embedding
            except Exception as ex:
                logger.error(f"OpenRouter embedding request failed on attempt {attempt + 1}: {ex}", exc_info=True)
                if attempt < max_retries - 1:
                    time.sleep(self._backoff_delay(attempt))

        raise RuntimeError("Failed to generate embedding after retries")


openrouter = OpenRouterService()
