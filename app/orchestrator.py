"""
Pipeline coordinator for book generation.

Each step validates preconditions before proceeding and persists state
to disk. Status transitions are enforced to prevent data inconsistencies.
"""
import logging
import re
from typing import List, Optional

from app.ai_client import AIClient
from app.storage import save_book
from app.schemas import BookState

logger = logging.getLogger(__name__)

# Valid status transition graph
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["summary_generated", "failed"],
    "summary_generated": ["outline_generated", "failed"],
    "outline_generated": ["in_progress", "failed"],
    "in_progress": ["completed", "failed"],
    "completed": ["failed"],
    "failed": ["pending"],  # allow retry
}


# Length-to-chapter-count guidance
LENGTH_CHAPTER_COUNT: dict[str, str] = {
    "short_story": "1",
    "novella": "3-5",
    "novel": "8-15",
    "epic": "15-25",
}

# Length-to-word-count guidance
LENGTH_WORD_COUNT: dict[str, str] = {
    "short_story": "1,000–7,500",
    "novella": "7,500–20,000",
    "novel": "20,000–50,000",
    "epic": "50,000+",
}


def _transition(book_state: BookState, new_status: str):
    """
    Transition book_state to a new status only if the transition is valid
    and the required data is present.
    """
    allowed = VALID_TRANSITIONS.get(book_state.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Invalid status transition: '{book_state.status}' → '{new_status}'. "
            f"Allowed: {allowed}"
        )
    book_state.status = new_status


class Orchestrator:
    def __init__(self, ai_client: AIClient):
        self.ai_client = ai_client

    def validate_book(self, book_state: BookState) -> dict:
        """
        Validate that the book content meets the necessary constraints.
        Returns {"valid": bool, "errors": list[str]}.
        """
        errors = []
        if not book_state.summary:
            errors.append("Summary is missing.")
        if not book_state.outline:
            errors.append("Outline is missing.")
        if book_state.outline and book_state.chapters and len(book_state.chapters) != len(book_state.outline):
            errors.append(
                f"Chapter count ({len(book_state.chapters)}) does not match the outline ({len(book_state.outline)})."
            )
        if book_state.outline and not book_state.chapters:
            errors.append("Chapters are missing.")
        if book_state.chapters and not book_state.outline:
            errors.append("Outline is missing but chapters exist.")

        return {"valid": len(errors) == 0, "errors": errors}

    async def generate_summary(self, book_state: BookState):
        """Generate a book summary from the user's prompt."""
        if book_state.status != "pending":
            raise ValueError(f"Cannot generate summary: book is in '{book_state.status}' status (expected 'pending')")

        tags_str = ", ".join(book_state.tags) if book_state.tags else "none specified"
        length_word = book_state.length or "novel"

        system_prompt = (
            "You are a helpful assistant that generates detailed book summaries based on a user's prompt. "
            "Write a comprehensive summary (2-3 paragraphs) that captures the main themes, plot points, "
            "and key characters of the book."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Please generate a book summary for the following topic/prompt:\n\n"
                f"Title: {book_state.title}\n"
                f"Genre/Tags: {tags_str}\n"
                f"Book length: {length_word}\n\n"
                f"Prompt:\n{book_state.prompt}"
            )},
        ]

        response = await self.ai_client.generate_completion(messages)
        summary = response["choices"][0]["message"]["content"].strip()

        book_state.summary = summary
        _transition(book_state, "summary_generated")
        book_state.progress["current_step"] = "summary_generated"
        book_state.progress["percentage"] = 25

        save_book(book_state.id, book_state)
        return summary

    def _parse_outline(self, outline_content: str) -> List[str]:
        """
        Parse chapter titles from LLM output. Tries JSON first, then falls back
        to line-based parsing with heuristic marker detection.

        Handles various LLM output formats:
        - JSON arrays: ["Chapter 1: Title", "Chapter 2: Title"]
        - Numbered lists: 1. Title, 2. Title
        - Markdown headings: # Chapter 1, ## Chapter 2
        - Bullet lists: - Title, * Title
        """
        import json

        # Clean up markdown code blocks
        clean = outline_content.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            if len(parts) >= 2:
                clean = parts[1]
            # Strip language label
            first_newline = clean.find("\n")
            if first_newline > 0 and clean[:first_newline].strip().isalpha():
                clean = clean[first_newline + 1:]
            clean = clean.strip()

        # Try JSON array
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, list):
                chapters = [str(item).strip() for item in parsed if str(item).strip()]
                if chapters:
                    return chapters
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: line-based parsing
        lines = outline_content.split('\n')
        chapters = []
        for line in lines:
            clean_line = line.strip()
            if not clean_line:
                continue

            # Skip markdown code fence markers
            if clean_line.startswith("```"):
                continue

            # Detect various list markers
            parsed_title = None

            # Numbered: "1. Title", "Chapter 1: Title", "1) Title"
            num_match = re.match(r'^(\d+[.)]\s+)(.+)$', clean_line)
            if num_match:
                parsed_title = num_match.group(2).strip()

            # Markdown heading: "# Chapter 1: Title"
            if not parsed_title:
                heading_match = re.match(r'^#{1,6}\s+(.+)$', clean_line)
                if heading_match:
                    parsed_title = heading_match.group(1).strip()

            # Bullet: "- Title" or "* Title"
            if not parsed_title:
                bullet_match = re.match(r'^[-*]\s+(.+)$', clean_line)
                if bullet_match:
                    parsed_title = bullet_match.group(1).strip()

            # Plain line that looks like a chapter title
            if not parsed_title and len(clean_line) > 3:
                # Only treat as chapter if it looks meaningful
                if any(marker in clean_line.lower() for marker in ['chapter', 'part', 'section', 'prologue', 'epilogue']):
                    parsed_title = clean_line

            if parsed_title:
                chapters.append(parsed_title)

        if not chapters:
            # Last resort: split on newlines and use non-empty lines
            chapters = [l.strip() for l in lines if l.strip() and not l.strip().startswith('`')]

        return chapters if chapters else ["Chapter 1", "Chapter 2", "Chapter 3"]

    async def generate_outline(self, book_state: BookState):
        """Generate chapter outline from the summary."""
        if book_state.status != "summary_generated":
            raise ValueError(
                f"Cannot generate outline: book is in '{book_state.status}' status (expected 'summary_generated')"
            )
        if not book_state.summary:
            raise ValueError("Cannot generate outline: summary is missing")

        tags_str = ", ".join(book_state.tags) if book_state.tags else "none specified"
        length = book_state.length or "novel"
        chapter_count = LENGTH_CHAPTER_COUNT.get(length, "8-15")

        system_prompt = (
            "You are a helpful assistant that generates a book outline (a list of chapter titles) "
            "based on the provided summary. Return ONLY a JSON list of strings containing the chapter titles."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Given this summary:\n\n{book_state.summary}\n\n"
                f"Genre/Tags: {tags_str}\n"
                f"Book length: {length}\n\n"
                f"Please generate a list of chapters for this book. "
                f"Target: {chapter_count} chapter(s). "
                f"Return the output as a JSON array of strings, e.g., "
                f'["Chapter 1: Title", "Chapter 2: Title"]. '
                f"Do not include any other text or explanations."
            )},
        ]

        response = await self.ai_client.generate_completion(messages)
        outline_content = response["choices"][0]["message"]["content"]
        outline = self._parse_outline(outline_content)

        book_state.outline = outline
        _transition(book_state, "outline_generated")
        book_state.progress["current_step"] = "outline_generated"
        book_state.progress["total_chapters"] = len(outline)
        book_state.progress["percentage"] = 50

        save_book(book_state.id, book_state)
        return outline

    async def generate_chapters(self, book_state: BookState):
        """Generate all chapters from the outline."""
        if book_state.status != "outline_generated":
            raise ValueError(
                f"Cannot generate chapters: book is in '{book_state.status}' status (expected 'outline_generated')"
            )
        if not book_state.outline:
            raise ValueError("Cannot generate chapters: outline is missing")

        _transition(book_state, "in_progress")
        book_state.chapters = {}
        book_state.progress["current_step"] = "in_progress"
        book_state.progress["chapters_completed"] = 0

        tags_str = ", ".join(book_state.tags) if book_state.tags else "none specified"
        length = book_state.length or "novel"
        word_count = LENGTH_WORD_COUNT.get(length, "20,000-50,000")

        total = len(book_state.outline)
        for idx, chapter in enumerate(book_state.outline, 1):
            system_prompt = (
                "You are a skilled writer. Write a full, engaging book chapter based on the provided "
                "summary and chapter title. The chapter should be well-structured with proper paragraphs, "
                "dialogue, and descriptive prose."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"Book summary:\n{book_state.summary}\n\n"
                    f"Genre/Tags: {tags_str}\n"
                    f"Book length: {length} (target: {word_count} words total)\n\n"
                    f"Write the full content for this chapter:\n\n**{chapter}**\n\n"
                    f"This is chapter {idx} of {total}. "
                    f"Continue the story naturally from the previous chapters."
                )},
            ]

            response = await self.ai_client.generate_completion(messages)
            content = response["choices"][0]["message"]["content"].strip()
            book_state.chapters[chapter] = content

            # Update progress
            book_state.progress["chapters_completed"] = idx
            book_state.progress["percentage"] = 50 + int((idx / total) * 50)
            save_book(book_state.id, book_state)

        _transition(book_state, "completed")
        book_state.progress["current_step"] = "completed"
        book_state.progress["percentage"] = 100
        save_book(book_state.id, book_state)

        return book_state.chapters
