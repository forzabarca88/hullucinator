"""
Book generation pipeline: summary → outline → chapters.

Each step validates preconditions, persists state to disk, and
enforces valid status transitions.
"""
import logging
from typing import Dict, Any

from app.ai_client import AIClient, _extract_content, _unwrap_json_content
from app.storage import save_book
from app.schemas import BookState
from app.status import _transition, is_terminal_status
from app.parsing import parse_outline
from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config — single source of truth
_shared_config = get_default_shared_config()
_gen_config = _shared_config.generation

def _unwrap_json_content(text: str) -> str:
    """If text looks like JSON wrapping plain content, extract the inner text.
    
    Returns the original text if it's not valid JSON or doesn't contain
    a recognizable content wrapper.
    """
    import json
    # Try parsing as JSON
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text

    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "\n".join(str(item) for item in data).strip()
    if isinstance(data, dict):
        # Check common keys for wrapped content
        for key in ("content", "text", "body", "response", "output"):
            if key in data:
                return str(data[key]).strip()
        # "chapters" key means the LLM returned JSON when asked for plain text
        if "chapters" in data and isinstance(data["chapters"], list):
            return "\n\n".join(str(c) for c in data["chapters"]).strip()
        # Last resort: serialize the whole dict back
        return json.dumps(data, indent=2)
    return text


# Length-to-chapter-count guidance (derived from shared config)
LENGTH_CHAPTER_COUNT: dict[str, str] = {
    l.key: l.chapter_range for l in _shared_config.lengths
}

# Length-to-word-count guidance (derived from shared config)
LENGTH_WORD_COUNT: dict[str, str] = {
    l.key: l.word_range for l in _shared_config.lengths
}


def _format_chapter_guidance(chapter_range: str) -> str:
    """Convert chapter range to explicit constraint language for LLM prompts.

    '1' -> 'exactly 1 chapter'
    '3-5' -> 'between 3 and 5 chapters'
    '8-15' -> 'between 8 and 15 chapters'
    '15-25' -> 'between 15 and 25 chapters'
    """
    if '-' not in chapter_range:
        return f"exactly {chapter_range} chapter" if chapter_range == "1" else f"exactly {chapter_range} chapters"
    parts = chapter_range.split('-')
    return f"between {parts[0]} and {parts[1]} chapters"


def _parse_chapter_range(chapter_range: str) -> tuple:
    """Parse a chapter range string into (min_chapters, max_chapters).

    '1' -> (1, 1)
    '3-5' -> (3, 5)
    '8-15' -> (8, 15)
    '15-25' -> (15, 25)
    """
    if '-' not in chapter_range:
        n = int(chapter_range)
        return n, n
    parts = chapter_range.split('-')
    return int(parts[0]), int(parts[1])


def _update_progress(book: BookState, current_step: str, percentage: int = 0,
                     total_chapters: int = 0, chapters_completed: int = 0) -> None:
    """Update progress tracking fields on a book state."""
    book.progress["current_step"] = current_step
    book.progress["total_chapters"] = total_chapters
    book.progress["chapters_completed"] = chapters_completed
    book.progress["percentage"] = percentage


async def generate_summary(ai_client: AIClient, book: BookState) -> None:
    """Generate a book summary from the user prompt."""
    if book.status != "pending":
        raise ValueError(f"Cannot generate summary: book is '{book.status}', expected 'pending'")

    tags_str = ", ".join(book.tags) if book.tags else "no specific genre"

    messages = [
        {"role": "system", "content": (
            _gen_config.summary_system_prompt.format(length=book.length, tags=tags_str)
        )},
        {"role": "user", "content": (
            f"Title: {book.title}\n"
            f"Genre/Tags: {tags_str}\n"
            f"Book length: {book.length} ({LENGTH_WORD_COUNT.get(book.length, 'unknown')} words)\n\n"
            f"User prompt:\n{book.prompt}\n\n"
            f"Generate a single paragraph summary that captures the core premise, "
            f"main conflict, and overall direction of the book."
        )},
    ]

    _update_progress(book, "Generating summary...", percentage=10)
    save_book(book.id, book)

    response = await ai_client.generate_completion(messages, temperature=_gen_config.summary_temperature)
    summary = _extract_content(response)

    book.summary = summary
    _transition(book, "summary_generated")
    _update_progress(book, "Summary generated", percentage=20)
    save_book(book.id, book)

    logger.info("Summary generated for '%s' (%s): %d chars", book.title, book.id, len(summary))


async def generate_outline(ai_client: AIClient, book: BookState) -> None:
    """Generate a chapter outline from the book summary."""
    if book.status != "summary_generated":
        raise ValueError(f"Cannot generate outline: book is '{book.status}', expected 'summary_generated'")

    tags_str = ", ".join(book.tags) if book.tags else "no specific genre"
    chapter_range = LENGTH_CHAPTER_COUNT.get(book.length, "8-15")
    chapter_guidance = _format_chapter_guidance(chapter_range)
    word_guidance = LENGTH_WORD_COUNT.get(book.length, "20,000-50,000")

    messages = [
        {"role": "system", "content": (
            _gen_config.outline_system_prompt.format(
                length=book.length, word_count=word_guidance, tags=tags_str, chapter_guidance=chapter_guidance
            )
        )},
        {"role": "user", "content": (
            f"Title: {book.title}\n"
            f"Genre/Tags: {tags_str}\n"
            f"Book length: {book.length}\n"
            f"Number of chapters: {chapter_guidance}\n"
            f"Target word count: {word_guidance}\n\n"
            f"Summary:\n{book.summary}\n\n"
            f"Generate a chapter-by-chapter outline as a numbered list. "
            f"Return ONLY the list, one chapter per line, in this format:\n"
            f"1. Chapter Title One\n"
            f"2. Chapter Title Two\n\n"
            f"IMPORTANT: The outline must contain {chapter_guidance}. Do not add extra chapters. "
            f"Do NOT wrap the output in JSON. Do NOT include any explanatory text. "
            f"Each chapter title should be descriptive and indicate the main focus of that chapter. "
            f"The outline should show a clear narrative arc from beginning to end."
        )},
    ]

    _update_progress(book, "Generating outline...", percentage=30)
    save_book(book.id, book)

    response = await ai_client.generate_completion(messages, temperature=_gen_config.outline_temperature)
    outline_chapters = parse_outline(response, [])

    # Enforce chapter count to match the length tier
    min_chapters, max_chapters = _parse_chapter_range(chapter_range)
    if len(outline_chapters) > max_chapters:
        logger.warning("Outline for '%s' has %d chapters but %s allows max %d — trimming", book.title, len(outline_chapters), book.length, max_chapters)
        outline_chapters = outline_chapters[:max_chapters]
    elif len(outline_chapters) < min_chapters:
        logger.warning("Outline for '%s' has %d chapters but %s requires min %d", book.title, len(outline_chapters), book.length, min_chapters)

    # Store outline as list (matching BookState schema)
    book.outline = outline_chapters
    book.chapters = {}  # Will be populated during chapter generation
    book.chapter_summaries = {}

    _transition(book, "outline_generated")
    _update_progress(book, "Outline generated", total_chapters=len(outline_chapters), percentage=40)
    save_book(book.id, book)

    logger.info("Outline generated for '%s' (%s): %d chapters", book.title, book.id, len(outline_chapters))


async def generate_chapters(ai_client: AIClient, book: BookState) -> None:
    """Generate all chapters sequentially with cumulative context."""
    if book.status != "outline_generated":
        raise ValueError(f"Cannot generate chapters: book is '{book.status}', expected 'outline_generated'")

    # Outline is stored as list of chapter titles
    chapter_titles = book.outline

    if not chapter_titles:
        raise ValueError("No chapters found in outline")

    tags_str = ", ".join(book.tags) if book.tags else "no specific genre"
    word_guidance = LENGTH_WORD_COUNT.get(book.length, "2,500-4,000")

    _transition(book, "in_progress")
    total = len(chapter_titles)
    _update_progress(book, "Generating chapters...", total_chapters=total, chapters_completed=0, percentage=40)
    save_book(book.id, book)

    for i, title in enumerate(chapter_titles):
        chapter_num = i + 1

        # Build cumulative context
        context_parts = [
            f"Book: {book.title}\n",
            f"Genre: {tags_str}\n",
            f"Book Summary:\n{book.summary}\n\n",
            f"Full Outline:\n{book.outline}\n\n",
        ]

        # Add summaries of previously generated chapters
        if book.chapter_summaries:
            context_parts.append("Previous Chapter Summaries:\n")
            for prev_title, summary in book.chapter_summaries.items():
                context_parts.append(f"- {prev_title}: {summary}\n")
            context_parts.append("\n")

        messages = [
            {"role": "system", "content": (
                _gen_config.chapter_system_prompt.format(
                    chapter_num=chapter_num, length=book.length, tags=tags_str, word_count=word_guidance
                )
            )},
            {"role": "user", "content": (
                "".join(context_parts) +
                f"Now write: {title}\n\n"
                f"Continue the story naturally from the previous chapters. "
                f"Maintain consistent tone, character voices, and narrative pacing. "
                f"Target word count for this chapter: {word_guidance}.\n\n"
                f"Return ONLY the chapter content as plain text, starting directly with the narrative."
            )},
        ]

        _update_progress(book, f"Writing {title}...", total_chapters=total, chapters_completed=i,
                         percentage=40 + int(i / total * 30))
        save_book(book.id, book)

        response = await ai_client.generate_completion(messages, temperature=_gen_config.chapter_temperature)
        chapter_content = _extract_content(response)
        # Unwrap JSON if the LLM returned JSON despite being asked for plain text
        chapter_content = _unwrap_json_content(chapter_content)

        if not chapter_content or len(chapter_content.strip()) < _gen_config.min_chapter_chars:
            raise ValueError(f"Chapter '{title}' generation produced insufficient content")

        book.chapters[title] = chapter_content

        # Generate chapter summary for continuity
        book.chapter_summaries[title] = await _summarize_chapter(ai_client, chapter_content, title)

        _update_progress(book, f"Completed {title}", total_chapters=total, chapters_completed=i + 1,
                         percentage=40 + int((i + 1) / total * 30))
        save_book(book.id, book)

        logger.info("Chapter %d/%d '%s' generated (%d chars)",
                     chapter_num, total, title, len(chapter_content))

    _transition(book, "completed")
    _update_progress(book, "All chapters generated", total_chapters=total, chapters_completed=total, percentage=70)
    save_book(book.id, book)

    logger.info("All %d chapters generated for '%s' (%s)", total, book.title, book.id)


async def _summarize_chapter(ai_client: AIClient, chapter_content: str, chapter_title: str) -> str:
    """
    Generate a concise one-paragraph summary of a chapter.
    Used to provide continuity context for subsequent chapters.
    """
    messages = [
        {"role": "system", "content": _gen_config.chapter_summary_system_prompt},
        {"role": "user", "content": (
            f"Chapter: {chapter_title}\n\n"
            f"Content:\n{chapter_content}\n\n"
            f"Provide only the summary paragraph, nothing else."
        )},
    ]

    response = await ai_client.generate_completion(messages, temperature=_gen_config.chapter_summary_temperature)
    return _extract_content(response)
