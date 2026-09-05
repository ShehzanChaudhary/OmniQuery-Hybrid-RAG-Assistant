## Importing Libraries
import json
import asyncio
from typing import AsyncGenerator, Optional
from langfuse import observe, propagate_attributes
from src.model import Conversation, Message
from src.adapters.openrouter import openrouter
from src.adapters.chroma_db import chroma_db
from src.adapters.sqlite_db import sqlite_db
from src.adapters.sqlite_db import sqlite_db
from src.adapters.schema_index import schema_index, WIDE_TABLE_COLUMN_THRESHOLD
from src.utlis_helper import decode_json
from src.prompts import get_prompt_template
from src.adapters.logger import logger
from src.adapters.followup_tracker import followup_tracker
from src.adapters.response_cache import response_cache
from src.adapters.tracing import langfuse_client
from src.adapters.tavily_search import tavily_search


def _get_tables_schema(question: str) -> list[dict]:
    """
    Instead of dumping every table's full schema, retrieves only the tables
    relevant to this question (via embeddings), and for wide tables, only
    the relevant columns too — keeps the prompt small regardless of scale.
    """
    relevant_table_names = schema_index.get_relevant_tables(question, top_k=5)

    result = []
    for table_name in relevant_table_names:
        columns = sqlite_db.get_schema(table_name)

        if len(columns) > WIDE_TABLE_COLUMN_THRESHOLD:
            relevant_col_names = schema_index.get_relevant_columns(question, table_name, top_k=20)
            columns = [c for c in columns if c["name"] in relevant_col_names]

        result.append({"table_name": table_name, "columns": columns})

    return result

@observe(name="rephrase_query")
def _rephrase_query(conversation: Conversation, question: str) -> str:
    history_text = "\n".join(f"{msg.role}: {msg.content}" for msg in conversation.recent())

    if not history_text:
        return question

    system_prompt = get_prompt_template("rephrase_query.Jinja2").render(conversation_history=history_text)

    rephrased, _ = openrouter.chat([
        Message(role='system', content=system_prompt),
        Message(role='user', content=f"Question: {question}"),
    ], name="rephrase_query")

    rephrased = rephrased.strip()
    if rephrased.lower() == "not a follow-up question":
        return question

    logger.info(f"Rephrased question from '{question}' to '{rephrased}'")
    return rephrased


@observe(name="rephrase_query")
async def _rephrase_query_async(conversation: Conversation, question: str) -> str:
    history_text = "\n".join(f"{msg.role}: {msg.content}" for msg in conversation.recent())

    if not history_text:
        return question

    system_prompt = get_prompt_template("rephrase_query.Jinja2").render(conversation_history=history_text)

    rephrased, _ = await openrouter.achat([
        Message(role='system', content=system_prompt),
        Message(role='user', content=f"Question: {question}"),
    ], name="rephrase_query")

    rephrased = rephrased.strip()
    if rephrased.lower() == "not a follow-up question":
        return question

    logger.info(f"Rephrased question from '{question}' to '{rephrased}'")
    return rephrased


@observe(name="execute_sql", as_type="tool")
def _execute_sql(raw_query: str) -> list[dict]:
    return sqlite_db.execute_query(raw_query)


@observe(name="sql_flow", as_type="chain")
def _run_sql_flow(question: str) -> str:
    """
    Sync SQL pipeline: generate SQL from the question + schema, execute it,
    and turn the results into a natural-language answer.
    """
    tables = _get_tables_schema(question)

    ## Step A - Generate the SQL query
    sql_prompt = get_prompt_template("sql_generation.jinja2").render(tables=tables, question=question)
    raw_query, _ = openrouter.chat([Message(role='system', content=sql_prompt)], name="generate_sql")
    raw_query = raw_query.strip().strip("`").strip()

    if raw_query == "NOT_ANSWERABLE":
        return "Sorry, I couldn't find a way to answer that from the available tables."

    logger.info(f"Generated SQL for question '{question}': {raw_query}")

    ## Step B - Execute it (guarded — only SELECT allowed, enforced inside sqlite_db)
    try:
        results = _execute_sql(raw_query)
    except Exception as ex:
        logger.error(f"SQL execution failed for query '{raw_query}': {ex}")
        return "Sorry, I ran into an issue looking that up. Could you rephrase your question?"

    # If the result is huge, give LLM just the summary—not the entire dump.
    RESULT_PREVIEW_LIMIT = 20
    total_rows = len(results)
    if total_rows > RESULT_PREVIEW_LIMIT:
        results_for_llm = results[:RESULT_PREVIEW_LIMIT]
        summary_note = f"(Showing first {RESULT_PREVIEW_LIMIT} of {total_rows} total rows.)"
    else:
        results_for_llm = results
        summary_note = ""

    ## Step C - Turn results into a natural-language answer
    response_prompt = get_prompt_template("sql_response.jinja2").render(
    question=question,
    results=json.dumps(results_for_llm, default=str),
    summary_note=summary_note,
    )

    answer, tokens_used = openrouter.chat([Message(role='system', content=response_prompt)], name="sql_response")

    logger.info(f"SQL response generated: {answer} for question: {question}")
    return answer

async def _run_sql_flow_async(question: str, tables: list) -> AsyncGenerator[str, None]:
    """
    Async + streaming SQL pipeline. Query generation and execution happen
    non-streamed (they're fast, background steps); only the final natural
    -language answer is streamed to the user.
    """
    with langfuse_client.start_as_current_observation(
        name="sql_flow", as_type="chain", input={"question": question},
    ) as chain:
        answer_parts = []
        try:
            ## Step A - Generate the SQL query
            sql_prompt = get_prompt_template("sql_generation.jinja2").render(tables=tables, question=question)
            raw_query, _ = await openrouter.achat([Message(role='system', content=sql_prompt)], name="generate_sql")
            raw_query = raw_query.strip().strip("`").strip()

            if raw_query == "NOT_ANSWERABLE":
                msg = "Sorry, I couldn't find a way to answer that from the available tables."
                yield msg
                answer_parts.append(msg)
                return

            logger.info(f"Generated SQL for question '{question}': {raw_query}")

            ## Step B - Execute it (sqlite3 is sync, so run it in a thread)
            try:
                results = await asyncio.to_thread(_execute_sql, raw_query)
            except Exception as ex:
                logger.error(f"SQL execution failed for query '{raw_query}': {ex}")
                msg = "Sorry, I ran into an issue looking that up. Could you rephrase your question?"
                yield msg
                answer_parts.append(msg)
                return

            # If the result is huge, give LLM just the summary—not the entire dump.
            RESULT_PREVIEW_LIMIT = 20  ## column*row limit for LLM to process, rest will be truncated
            total_rows = len(results)
            if total_rows > RESULT_PREVIEW_LIMIT:
                results_for_llm = results[:RESULT_PREVIEW_LIMIT]
                summary_note = f"(Showing first {RESULT_PREVIEW_LIMIT} of {total_rows} total rows.)"
            else:
                results_for_llm = results
                summary_note = ""

            ## Step C - Stream the natural-language answer
            response_prompt = get_prompt_template("sql_response.jinja2").render(
            question=question,
            results=json.dumps(results_for_llm, default=str),
            summary_note=summary_note,
        )

            async for chunk in openrouter.stream_chat([Message(role='system', content=response_prompt)], name="sql_response"):
                answer_parts.append(chunk)
                yield chunk
        finally:
            chain.update(output="".join(answer_parts))

def _get_previous_question(conversation: Conversation) -> Optional[str]:
    """Returns the last user message in this session, if any (used to record transitions)."""
    for msg in reversed(conversation.messages):
        if msg.role == 'user':
            return msg.content
    return None

@observe(name="followup_questions", as_type="tool")
def _get_followup_questions(question: str, answer: str) -> list[str]:
    """
     Hybrid: first checks if popular follow-ups exist from real usage history
    (no LLM call needed). Falls back to LLM generation for new/rare questions.
    """
    popular = followup_tracker.get_popular_followups(question)
    if popular:
        logger.info(f"Using popular (history-based) follow-ups for: {question}")
        return popular

    try:
        prompt = get_prompt_template("followup_questions.jinja2").render(question=question, answer=answer)
        response, _ = openrouter.chat([Message(role='system', content=prompt)], json_mode=True, name="followup_questions_llm")
        questions = decode_json(response).get("questions", [])
        logger.info(f"LLM-generated follow-up questions: {questions}")
        return questions[:3] if isinstance(questions, list) else []
    except Exception as ex:
        logger.error(f"Failed to generate follow-up questions: {ex}")
        return []


@observe(name="followup_questions", as_type="tool")
async def _get_followup_questions_async(question: str, answer: str) -> list[str]:
    popular = await asyncio.to_thread(followup_tracker.get_popular_followups, question)
    if popular:
        logger.info(f"Using popular (history-based) follow-ups for: {question}")
        return popular

    try:
        prompt = get_prompt_template("followup_questions.jinja2").render(question=question, answer=answer)
        response, _ = await openrouter.achat([Message(role='system', content=prompt)], json_mode=True, name="followup_questions_llm")
        questions = decode_json(response).get("questions", [])
        logger.info(f"LLM-generated follow-up questions: {questions}")
        return questions[:3] if isinstance(questions, list) else []
    except Exception as ex:
        logger.error(f"Failed to generate follow-up questions: {ex}")
        return []

def generate_final_response(question: str, session_id: Optional[str] = None) -> tuple[str, int, str]:
    conversation = Conversation(session_id=session_id, history_turns=3)

    with langfuse_client.start_as_current_observation(
        name=f"query: {question[:80]}",
        as_type="span",
        input={"question": question},
    ) as root:
        question_id = langfuse_client.get_current_trace_id()
        root.set_trace_io(input={"question": question})

        with propagate_attributes(
            session_id=conversation.session_id,
            metadata={"question_id": question_id},
        ):
            previous_question = _get_previous_question(conversation)
            if previous_question:
                try:
                    followup_tracker.record_transition(previous_question, question)
                except Exception as ex:
                    logger.error(f"Failed to record question transition: {ex}")

            is_first_turn = len(conversation.messages) == 0  # Cache only for fresh session

            ## Step 1 - Rephrase using conversation history (no-op when there's none yet)
            rephrased_question = _rephrase_query(conversation, question)

            ## Step 2 - Cache check, against the rephrased/normalized question
            with langfuse_client.start_as_current_observation(
                name="cache_lookup", as_type="tool", input={"question": rephrased_question},
            ) as cache_span:
                cached = response_cache.get_cached_answer(rephrased_question) if is_first_turn else None
                cache_span.update(output={"hit": cached is not None})

            tokens_used = 0

            if cached:
                logger.info(f"Cache hit for question: {question}")
                intent = None
                with propagate_attributes(tags=["cache_hit"]):
                    answer = cached
                    answer_for_history = answer
                    followup_questions = _get_followup_questions(question, answer)

            else:
                ## Step 3 - Determine intent, then run the matching flow
                tables = _get_tables_schema(rephrased_question)
                system_prompt = get_prompt_template("intent_check.Jinja2").render(tables=tables)

                response, _ = openrouter.chat([
                    Message(role='system', content=system_prompt),
                    Message(role='user', content=rephrased_question),
                ], json_mode=True, name="intent_check")

                intent = decode_json(response).get('intent')
                logger.info(f"Intent determined: {intent} for question: {question}")

                with propagate_attributes(tags=[intent]):
                    if intent == 'greeting':
                        system_prompt = get_prompt_template("greeting.Jinja2").render()

                        answer, tokens_used = openrouter.chat([
                            Message(role='system', content=system_prompt),
                            Message(role='user', content=rephrased_question),
                        ], name="greeting_response")
                        logger.info(f"Greeting response generated: {answer} for question: {question}")
                        answer_for_history = answer
                        followup_questions = []

                    elif intent == 'sql_question':
                        answer = _run_sql_flow(rephrased_question)
                        answer_for_history = answer

                        if is_first_turn:
                            response_cache.set_cached_answer(rephrased_question, answer)

                        followup_questions = _get_followup_questions(question, answer)

                    elif intent == 'web_search_question':
                        cached = response_cache.get_cached_answer(question) if is_first_turn else None
                        if cached:
                            logger.info(f"Cache hit for web search question: {question}")
                            answer = cached
                        else:
                            search_results = tavily_search.search(question)

                            if not search_results:
                                answer = "Sorry, I couldn't find any relevant information from the web right now."
                            else:
                                prompt = get_prompt_template("web_search_response.jinja2").render(
                                    question=question,
                                    results=search_results,
                                )
                                answer, tokens_used = openrouter.chat([Message(role='system', content=prompt)])
                                logger.info(f"Web search response generated: {answer} for question: {question}")

                                citation_lines = [f"[{r['title']}]({r['url']})" for r in search_results if r.get('url')]
                                if citation_lines:
                                    answer += f"\n\n**Sources:** {'; '.join(citation_lines)}"

                            if is_first_turn:
                                response_cache.set_cached_answer(question, answer)

                        answer_for_history = answer
                        followup_questions = _get_followup_questions(question, answer)

                    else:   # document_question
                        prompt_template = get_prompt_template("final_response.jinja2")

                        with langfuse_client.start_as_current_observation(
                            name="retrieve_chunks", as_type="retriever", input={"query": rephrased_question},
                        ) as retriever:
                            retrieved_chunks = chroma_db.fetch_chunks(query=rephrased_question, top_k=4)
                            retriever.update(output=[
                                {"filename": c.metadata.get("filename"), "page": c.metadata.get("page"), "distance": c.distance}
                                for c in retrieved_chunks
                            ])

                        context_text = "\n\n".join(chunk.text for chunk in retrieved_chunks)
                        history_text = "\n".join(f"{msg.role}: {msg.content}" for msg in conversation.recent())

                        rendered_prompt = prompt_template.render(
                            context=context_text,
                            conversation_history=history_text,
                            question=rephrased_question,
                        )
                        answer, tokens_used = openrouter.chat([Message(role='system', content=rendered_prompt)], name="final_response")
                        logger.info(f"Final response generated: {answer} for question: {question} (rephrased as: {rephrased_question})")

                        answer_for_history = answer

                        # Collect citations
                        citations = {}
                        for chunk in retrieved_chunks:
                            filename = chunk.metadata.get('filename', 'Unknown Document')
                            page = chunk.metadata.get('page')
                            citations.setdefault(filename, set()).add(page)

                        if citations:
                            citation_lines = []
                            for filename, pages in citations.items():
                                sorted_pages = sorted(p for p in pages if p is not None)
                                page_str = ", ".join(f"Page {p}" for p in sorted_pages)
                                citation_lines.append(f"{filename} ({page_str})")
                            answer += f"\n\n**Sources:** {'; '.join(citation_lines)}"

                        if is_first_turn:
                            response_cache.set_cached_answer(rephrased_question, answer)

                        followup_questions = _get_followup_questions(question, answer)

        # Step 4 - Save the turn to this session's history
        conversation.add('user', question)
        conversation.add('assistant', answer_for_history)

        root.set_trace_io(output=answer)
        root.update(metadata={"tokens_used": tokens_used, "intent": intent})

        return answer, tokens_used, conversation.session_id, followup_questions


async def generate_final_response_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[str, None]:
    conversation = Conversation(session_id=session_id, history_turns=3)

    with langfuse_client.start_as_current_observation(
        name=f"query: {question[:80]}",
        as_type="span",
        input={"question": question},
    ) as root:
        question_id = langfuse_client.get_current_trace_id()
        root.set_trace_io(input={"question": question})

        with propagate_attributes(
            session_id=conversation.session_id,
            metadata={"question_id": question_id},
        ):
            previous_question = _get_previous_question(conversation)
            if previous_question:
                try:
                    await asyncio.to_thread(followup_tracker.record_transition, previous_question, question)
                except Exception as ex:
                    logger.error(f"Failed to record question transition: {ex}")

            is_first_turn = len(conversation.messages) == 0
            full_answer_parts = []

            ## Step 1 - Rephrase using conversation history (no-op when there's none yet)
            rephrased_question = await _rephrase_query_async(conversation, question)

            ## Step 2 - Cache check, against the rephrased/normalized question
            with langfuse_client.start_as_current_observation(
                name="cache_lookup", as_type="tool", input={"question": rephrased_question},
            ) as cache_span:
                cached = await asyncio.to_thread(response_cache.get_cached_answer, rephrased_question) if is_first_turn else None
                cache_span.update(output={"hit": cached is not None})

            if cached:
                logger.info(f"Cache hit for question: {question}")
                intent = None
                with propagate_attributes(tags=["cache_hit"]):
                    answer = cached
                    yield answer
                    full_answer_parts.append(answer)
                    answer_for_history = answer
                    followup_questions = await _get_followup_questions_async(question, answer)

            else:
                ## Step 3 - Determine intent, then run the matching flow
                tables = _get_tables_schema(rephrased_question)
                system_prompt = get_prompt_template('intent_check.Jinja2').render(tables=tables)

                response, _ = await openrouter.achat([
                    Message(role='system', content=system_prompt),
                    Message(role='user', content=rephrased_question)
                ], json_mode=True, name="intent_check")

                intent = decode_json(response).get('intent')
                logger.info(f'Intent determined: {intent} for question: {question}')

                with propagate_attributes(tags=[intent]):
                    if intent == 'greeting':
                        system_prompt = get_prompt_template('greeting.Jinja2').render()

                        answer, _ = await openrouter.achat([
                            Message(role='system', content=system_prompt),
                            Message(role='user', content=rephrased_question)
                        ], name="greeting_response")
                        logger.info(f'Greeting response generated: {answer} for question: {question}')

                        yield answer
                        full_answer_parts.append(answer)
                        answer_for_history = answer
                        followup_questions = []

                    elif intent == 'sql_question':
                        answer_parts = []
                        async for chunk in _run_sql_flow_async(rephrased_question, tables):
                            answer_parts.append(chunk)
                            full_answer_parts.append(chunk)
                            yield chunk
                        answer = "".join(answer_parts)

                        if is_first_turn:
                            await asyncio.to_thread(response_cache.set_cached_answer, rephrased_question, answer)

                        answer_for_history = answer
                        followup_questions = await _get_followup_questions_async(question, answer)

                    elif intent == 'web_search_question':
                        cached = await asyncio.to_thread(response_cache.get_cached_answer, question) if is_first_turn else None
                        if cached:
                            logger.info(f"Cache hit for web search question: {question}")
                            answer = cached
                            yield answer
                        else:
                            search_results = await asyncio.to_thread(tavily_search.search, question)

                            if not search_results:
                                answer = "Sorry, I couldn't find any relevant information from the web right now."
                                yield answer
                            else:
                                prompt = get_prompt_template("web_search_response.jinja2").render(
                                    question=question,
                                    results=search_results,
                                )

                                answer_parts = []
                                async for chunk in openrouter.stream_chat([Message(role='system', content=prompt)]):
                                    answer_parts.append(chunk)
                                    yield chunk

                                answer = "".join(answer_parts)
                                logger.info(f"Web search response generated: {answer} for question: {question}")

                                citation_lines = [f"[{r['title']}]({r['url']})" for r in search_results if r.get('url')]
                                if citation_lines:
                                    citation_footer = f"\n\n**Sources:** {'; '.join(citation_lines)}"
                                    answer += citation_footer
                                    yield citation_footer

                            if is_first_turn:
                                await asyncio.to_thread(response_cache.set_cached_answer, question, answer)

                        answer_for_history = answer
                        followup_questions = await _get_followup_questions_async(question, answer)

                    else:   # document_question
                        with langfuse_client.start_as_current_observation(
                            name="retrieve_chunks", as_type="retriever", input={"query": rephrased_question},
                        ) as retriever:
                            retrieved_chunks = await chroma_db.afetch_chunks(query=rephrased_question, top_k=4)
                            retriever.update(output=[
                                {"filename": c.metadata.get("filename"), "page": c.metadata.get("page"), "distance": c.distance}
                                for c in retrieved_chunks
                            ])

                        context_text = '\n\n'.join(chunk.text for chunk in retrieved_chunks)
                        history_text = '\n'.join(f'{msg.role}: {msg.content}' for msg in conversation.recent())

                        prompt_template = get_prompt_template("final_response.jinja2")
                        rendered_prompt = prompt_template.render(
                            context=context_text,
                            conversation_history=history_text,
                            question=rephrased_question,
                        )

                        answer_parts = []
                        async for chunk in openrouter.stream_chat([Message(role='system', content=rendered_prompt)], name="final_response"):
                            answer_parts.append(chunk)
                            full_answer_parts.append(chunk)
                            yield chunk

                        answer = "".join(answer_parts)
                        logger.info(f"Final response generated: {answer} for question: {question} (rephrased as: {rephrased_question})")

                        answer_for_history = answer

                        # Collect citations
                        citations = {}
                        for chunk in retrieved_chunks:
                            filename = chunk.metadata.get("filename", "Unknown document")
                            page = chunk.metadata.get("page")
                            citations.setdefault(filename, set()).add(page)

                        if citations:
                            citation_lines = []
                            for filename, pages in citations.items():
                                sorted_pages = sorted(p for p in pages if p is not None)
                                page_str = ", ".join(f"Page {p}" for p in sorted_pages)
                                citation_lines.append(f"{filename} ({page_str})")
                            citation_footer = f"\n\n**Sources:** {'; '.join(citation_lines)}"
                            answer += citation_footer
                            full_answer_parts.append(citation_footer)
                            yield citation_footer

                        if is_first_turn:
                            await asyncio.to_thread(response_cache.set_cached_answer, rephrased_question, answer)

                        followup_questions = await _get_followup_questions_async(question, answer)

        # Step 4 - Save to this session's history
        conversation.add('user', question)
        conversation.add('assistant', answer_for_history)

        root.set_trace_io(output="".join(full_answer_parts))
        root.update(metadata={"intent": intent})

        yield f"__SESSION_ID__:{conversation.session_id}"
        yield f"__FOLLOWUPS__:{json.dumps(followup_questions)}"