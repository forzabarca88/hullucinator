"""
Book generation pipeline: summary → outline → chapters.

Each step validates preconditions, persists state to disk, and
enforces valid status transitions.
"""
import logging
from typing import Dict, Any

from app.ai_client import AIClient, _extract_content
from app.storage import save_book
from app.schemas import BookState
from app.status import _transition, is_terminal_status
from app.parsing import parse_outline
from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config — single source of truth
_shared_config = get_default_shared_config()

# Length-to-chapter-count guidance (derived from shared config)
LENGTH_CHAPTER_COUNT: dict[str, str] = {
    l.key: l.chapter_range for l in _shared_config.lengths
}

# Length-to-word-count guidance (derived from shared config)
LENGTH_WORD_COUNT: dict[str, str] = {
    l.key: l.word_range for l in _shared_config.lengths
}


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
            f"You are a creative writing assistant. Generate a compelling one-paragraph summary "
            f"for a {book.length} in the {tags_str} genre."
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

    response = await ai_client.generate_completion(messages, temperature=0.7)
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
    chapter_guidance = LENGTH_CHAPTER_COUNT.get(book.length, "8-15")
    word_guidance = LENGTH_WORD_COUNT.get(book.length, "20,000-50,000")

    messages = [
        {"role": "system", "content": (
            f"You are a creative writing assistant. Generate a chapter outline for a {book.length} "
            f"({word_guidance} words) in the {tags_str} genre."
        )},
        {"role": "user", "content": (
            f"Title: {book.title}\n"
            f"Genre/Tags: {tags_str}\n"
            f"Book length: {book.length}\n"
            f"Target chapters: {chapter_guidance}\n"
            f"Target word count: {word_guidance}\n\n"
            f"Summary:\n{book.summary}\n\n"
            f"Generate a chapter-by-chapter outline. Return as JSON with this exact structure:\n"
            f'{{"chapters": ["Chapter 1: Title", "Chapter 2: Title", ...]}}\n\n'
            f"Each chapter title should be descriptive and indicate the main focus of that chapter. "
            f"The outline should show a clear narrative arc from beginning to end."
        )},
    ]

    _update_progress(book, "Generating outline...", percentage=30)
    save_book(book.id, book)

    response = await ai_client.generate_completion(messages, temperature=0.7)
    outline_chapters = parse_outline(response, [])

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
                f"You are a creative writing assistant. Write chapter {chapter_num} of a {book.length} "
                f"in the {tags_str} genre. Target {word_guidance} words for the full book."
            )},
            {"role": "user", "content": (
                "".join(context_parts) +
                f"Now write: {title}\n\n"
                f"Continue the story naturally from the previous chapters. "
                f"Maintain consistent tone, character voices, and narrative pacing. "
                f"Target word count for this chapter: {word_guidance}.\n\n"
                f"Return ONLY the chapter content, starting directly with the narrative text."
            )},
        ]

        _update_progress(book, f"Writing {title}...", total_chapters=total, chapters_completed=i,
                         percentage=40 + int(i / total * 30))
        save_book(book.id, book)

        response = await ai_client.generate_completion(messages, temperature=0.8)
        chapter_content = _extract_content(response)

        if not chapter_content or len(chapter_content.strip()) < 100:
            raise ValueError(f"Chapter '{title}' generation produced insufficient content")

        book.chapters[title] = chapter_content

        # Generate chapter summary for continuity
        summary_messages = [
            {"role": "system", "content": "Summarize this chapter in one concise paragraph."},
            {"role": "user", "content": chapter_content},
        ]
        summary_response = await ai_client.generate_completion(summary_messages, temperature=0.3)
        book.chapter_summaries[title] = _extract_content(summary_response)

        _update_progress(book, f"Completed {title}", total_chapters=total, chapters_completed=i + 1,
                         percentage=40 + int((i + 1) / total * 30))
        save_book(book.id, book)

        logger.info("Chapter %d/%d '%s' generated (%d chars)",
                     chapter_num, total, title, len(chapter_content))

    _update_progress(book, "All chapters generated", total_chapters=total, chapters_completed=total, percentage=70)
    save_book(book.id, book)

    logger.info("All %d chapters generated for '%s' (%s)", total, book.title, book.id)
