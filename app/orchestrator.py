"""
Pipeline coordinator for book generation.

Each step validates preconditions before proceeding and persists state
to disk. Status transitions are enforced to prevent data inconsistencies.

Key features:
- Chapter continuity: each chapter receives cumulative context from prior chapters
- Post-completion review: professional critic reviews the finished book
- Iterative correction loop: critic reviews → corrections → re-review until approved
  or max turns reached
- Separate reviewer client: optional different endpoint/model for review tasks
- Full audit trail: per-turn review results stored in book metadata
"""
import logging
import re
import json
from typing import List, Optional

from app.ai_client import AIClient, ReviewerClient
from app.storage import save_book
from app.schemas import BookState

logger = logging.getLogger(__name__)

# Valid status transition graph
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["summary_generated", "failed"],
    "summary_generated": ["outline_generated", "failed"],
    "outline_generated": ["in_progress", "failed"],
    "in_progress": ["completed", "failed"],
    "completed": ["reviewing", "failed"],
    "reviewing": ["reviewed", "failed"],
    "reviewed": ["failed"],
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
    def __init__(self, ai_client: AIClient, reviewer_client: Optional[ReviewerClient] = None):
        self.ai_client = ai_client
        # Reviewer client for critique tasks (may use different endpoint/model)
        # If None, falls back to the main ai_client
        self.reviewer_client = reviewer_client

    def _get_reviewer(self) -> AIClient | ReviewerClient:
        """Return the client to use for review tasks."""
        return self.reviewer_client if self.reviewer_client else self.ai_client

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
        book_state.chapter_summaries = {}  # Initialize for continuity tracking
        _transition(book_state, "outline_generated")
        book_state.progress["current_step"] = "outline_generated"
        book_state.progress["total_chapters"] = len(outline)
        book_state.progress["percentage"] = 50

        save_book(book_state.id, book_state)
        return outline

    async def _generate_chapter(self, book_state: BookState, idx: int, chapter_title: str, total: int) -> str:
        """
        Generate a single chapter with full context from prior chapters.

        Context strategy: Each chapter receives:
        1. The book summary (overall direction)
        2. The full outline (structural awareness)
        3. Condensed summaries of all previously generated chapters (narrative continuity)

        This ensures each chapter flows naturally from what came before without
        consuming excessive tokens from full chapter text.
        """
        tags_str = ", ".join(book_state.tags) if book_state.tags else "none specified"
        length = book_state.length or "novel"
        word_count = LENGTH_WORD_COUNT.get(length, "20,000-50,000")

        # Build cumulative context from prior chapter summaries
        prior_context = ""
        if idx > 1 and book_state.chapter_summaries:
            # Include summaries of all prior chapters in order
            prior_parts = []
            for outline_title in book_state.outline[:idx - 1]:
                if outline_title in book_state.chapter_summaries:
                    prior_parts.append(f"  • {outline_title}: {book_state.chapter_summaries[outline_title]}")
            if prior_parts:
                prior_context = "\n\nPrevious chapters (summary of events so far):\n" + "\n".join(prior_parts)

        system_prompt = (
            "You are a skilled fiction writer. Write a full, engaging book chapter based on the provided "
            "context. The chapter should be well-structured with proper paragraphs, "
            "dialogue, and descriptive prose. Ensure it flows naturally from the previous chapters."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Book title: {book_state.title}\n"
                f"Genre/Tags: {tags_str}\n"
                f"Book length: {length} (target: {word_count} words total)\n\n"
                f"Book summary:\n{book_state.summary}\n\n"
                f"Full chapter outline:\n" + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(book_state.outline)) + "\n\n"
                + prior_context + "\n\n"
                f"Write the full content for chapter {idx} of {total}:\n\n**{chapter_title}**\n\n"
                f"Continue the story naturally from where the previous chapters left off. "
                f"Maintain consistent character voices, plot threads, and tone. "
                f"This chapter should advance the narrative meaningfully."
            )},
        ]

        response = await self.ai_client.generate_completion(messages, temperature=0.8)
        return response["choices"][0]["message"]["content"].strip()

    async def _summarize_chapter(self, chapter_content: str, chapter_title: str) -> str:
        """
        Generate a concise one-paragraph summary of a chapter.
        Used to provide continuity context for subsequent chapters.
        """
        messages = [
            {"role": "system", "content": (
                "You are a literary analyst. Summarize the following chapter in a single, concise paragraph "
                "(2-4 sentences) capturing the key events, character developments, and any plot threads "
                "that carry forward to the next chapter."
            )},
            {"role": "user", "content": (
                f"Chapter: {chapter_title}\n\n"
                f"Content:\n{chapter_content}\n\n"
                f"Provide only the summary paragraph, nothing else."
            )},
        ]

        response = await self.ai_client.generate_completion(messages, temperature=0.3)
        return response["choices"][0]["message"]["content"].strip()

    async def generate_chapters(self, book_state: BookState):
        """Generate all chapters from the outline, with continuity context."""
        if book_state.status != "outline_generated":
            raise ValueError(
                f"Cannot generate chapters: book is in '{book_state.status}' status (expected 'outline_generated')"
            )
        if not book_state.outline:
            raise ValueError("Cannot generate chapters: outline is missing")

        _transition(book_state, "in_progress")
        book_state.chapters = {}
        book_state.chapter_summaries = book_state.chapter_summaries or {}
        book_state.progress["current_step"] = "in_progress"
        book_state.progress["chapters_completed"] = 0

        total = len(book_state.outline)
        for idx, chapter_title in enumerate(book_state.outline, 1):
            logger.info("Generating chapter %d/%d: %s", idx, total, chapter_title)

            content = await self._generate_chapter(book_state, idx, chapter_title, total)
            book_state.chapters[chapter_title] = content

            # Generate a condensed summary for continuity context
            chapter_summary = await self._summarize_chapter(content, chapter_title)
            book_state.chapter_summaries[chapter_title] = chapter_summary
            logger.info("Chapter %d summary: %s", idx, chapter_summary[:80] + "...")

            # Update progress
            book_state.progress["chapters_completed"] = idx
            book_state.progress["percentage"] = 50 + int((idx / total) * 45)  # Reserve 5% for review
            save_book(book_state.id, book_state)

        _transition(book_state, "completed")
        book_state.progress["current_step"] = "completed"
        book_state.progress["percentage"] = 95
        save_book(book_state.id, book_state)

        return book_state.chapters

    async def review_book(self, book_state: BookState, max_turns: Optional[int] = None):
        """
        Review the completed book as a professional critic, running an
        iterative critique → correct → re-critique loop until the book
        passes review or max_turns is reached.

        Args:
            book_state: The book to review
            max_turns: Maximum review-correction iterations (defaults to book_state.review_max_turns)
        """
        if book_state.status not in ("completed", "reviewing"):
            raise ValueError(
                f"Cannot review book: book is in '{book_state.status}' status (expected 'completed' or 'reviewing')"
            )

        if not book_state.chapters or not book_state.summary:
            raise ValueError("Cannot review: book content is incomplete")

        if book_state.status == "completed":
            _transition(book_state, "reviewing")
            book_state.progress["current_step"] = "reviewing"
            book_state.progress["percentage"] = 97
            save_book(book_state.id, book_state)

        tags_str = ", ".join(book_state.tags) if book_state.tags else "none specified"
        reviewer = self._get_reviewer()
        turns_limit = max_turns if max_turns is not None else book_state.review_max_turns

        # Initialize review history
        if book_state.review_history is None:
            book_state.review_history = []

        logger.info("Starting iterative review for '%s' (max %d turns)...", book_state.title, turns_limit)

        for turn_num in range(1, turns_limit + 1):
            logger.info("Review turn %d/%d for '%s'", turn_num, turns_limit, book_state.title)

            # Update progress for UI
            if turn_num > 1:
                book_state.progress["current_step"] = f"reviewing (turn {turn_num})"
                book_state.progress["percentage"] = 97 + int((turn_num - 1) / turns_limit * 3)
                save_book(book_state.id, book_state)

            # Build the full book text for review
            review_text = f"Book: {book_state.title}\nGenre: {tags_str}\n\n"
            review_text += f"Summary:\n{book_state.summary}\n\n"
            review_text += "Outline:\n" + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(book_state.outline)) + "\n\n"

            for idx, (title, content) in enumerate(book_state.chapters.items(), 1):
                review_text += f"\n{'='*60}\nChapter {idx}: {title}\n{'='*60}\n{content}"

            # If this is turn > 1, include prior review results for context
            if turn_num > 1 and book_state.review_history:
                review_text += "\n\n--- Previous Review History ---\n"
                for prev in book_state.review_history:
                    review_text += f"\nTurn {prev['turn']}:\n"
                    review_text += f"  Score: {prev.get('overall_score', '?')}/10\n"
                    review_text += f"  Verdict: {prev.get('verdict', '?')}\n"
                    if prev.get('corrections'):
                        for corr in prev['corrections']:
                            review_text += f"  Corrected: '{corr['chapter']}' ({corr['issue_type']})\n"

            # Step 1: Professional critique (using reviewer client)
            critique_messages = [
                {"role": "system", "content": (
                    "You are a professional book critic and editor with decades of experience. "
                    "Review the following book critically. Identify any major issues including:\n"
                    "- Plot holes or logical inconsistencies\n"
                    "- Character inconsistencies (voice, motivation, development)\n"
                    "- Pacing problems (rushed sections, dragging sections)\n"
                    "- Continuity errors (events that contradict earlier chapters)\n"
                    "- Tone or style inconsistencies across chapters\n"
                    "- Unresolved plot threads or unsatisfying endings\n\n"
                    "Return your review as a JSON object with this exact structure:\n"
                    '{"issues": [{"chapter": "chapter_title", "type": "issue_type", "description": "what is wrong", "suggestion": "how to fix"}], "overall_score": 0-10, "verdict": "needs_revision" | "ready"}\n\n'
                    "Be constructive but honest. Only flag issues that would genuinely affect reader experience. "
                    "If the book is solid (score >= 7), set verdict to 'ready' with an empty issues array."
                )},
                {"role": "user", "content": review_text},
            ]

            critique_response = await reviewer.generate_completion(critique_messages, temperature=0.3)
            critique_raw = critique_response["choices"][0]["message"]["content"].strip()

            # Parse critique response
            critique_data = self._parse_critique(critique_raw)
            issues = critique_data.get("issues", [])
            overall_score = critique_data.get("overall_score", 5)
            verdict = critique_data.get("verdict", "needs_revision")

            # Step 2: If issues found, correct them (using writer client)
            corrections = []
            if verdict == "needs_revision" and issues:
                logger.info("Turn %d: Review found %d issues to correct", turn_num, len(issues))
                corrected_chapters = set()

                for issue in issues:
                    chapter_title = issue.get("chapter", "")
                    if not chapter_title or chapter_title not in book_state.chapters:
                        # If chapter title doesn't match, try fuzzy match
                        matched = self._match_chapter_title(chapter_title, book_state.chapters)
                        if matched:
                            chapter_title = matched
                        else:
                            logger.warning("Could not match issue chapter '%s' to any generated chapter", chapter_title)
                            continue

                    if chapter_title in corrected_chapters:
                        continue  # Already corrected this chapter

                    description = issue.get("description", "")
                    suggestion = issue.get("suggestion", "")

                    # Build revision context
                    prior_context = ""
                    if book_state.chapter_summaries:
                        prior_parts = []
                        for outline_title in book_state.outline:
                            if outline_title in book_state.chapter_summaries and outline_title != chapter_title:
                                prior_parts.append(f"  • {outline_title}: {book_state.chapter_summaries[outline_title]}")
                        if prior_parts:
                            prior_context = "\nPrior chapter summaries:\n" + "\n".join(prior_parts)

                    revision_messages = [
                        {"role": "system", "content": (
                            "You are a skilled fiction writer revising a chapter. Rewrite the chapter to address "
                            "the specific issues identified while preserving the core narrative and style. "
                            "Ensure consistency with the rest of the book."
                        )},
                        {"role": "user", "content": (
                            f"Book: {book_state.title}\nGenre: {tags_str}\n\n"
                            f"Book summary:\n{book_state.summary}\n\n"
                            + prior_context + "\n\n"
                            f"Issue identified in '{chapter_title}':\n"
                            f"  Type: {issue.get('type', 'general')}\n"
                            f"  Problem: {description}\n"
                            f"  Suggested fix: {suggestion}\n\n"
                            f"Current chapter content:\n{book_state.chapters[chapter_title]}\n\n"
                            f"Rewrite this chapter to address the issue. Return only the revised chapter content."
                        )},
                    ]

                    revision_response = await self.ai_client.generate_completion(revision_messages, temperature=0.7)
                    revised_content = revision_response["choices"][0]["message"]["content"].strip()

                    # Update chapter and regenerate its summary
                    book_state.chapters[chapter_title] = revised_content
                    new_summary = await self._summarize_chapter(revised_content, chapter_title)
                    book_state.chapter_summaries[chapter_title] = new_summary
                    corrected_chapters.add(chapter_title)

                    corrections.append({
                        "chapter": chapter_title,
                        "issue_type": issue.get("type", "general"),
                        "issue_description": description,
                        "suggestion": suggestion,
                        "corrected": True,
                    })

                    # Save after each correction
                    save_book(book_state.id, book_state)

                logger.info("Turn %d: Completed %d corrections", turn_num, len(corrected_chapters))
            else:
                logger.info("Turn %d: Book passed review (score: %d/10)", turn_num, overall_score)

            # Record this turn in history
            turn_record = {
                "turn": turn_num,
                "critique": critique_raw,
                "issues": issues,
                "overall_score": overall_score,
                "verdict": verdict,
                "corrections": corrections,
            }
            book_state.review_history.append(turn_record)
            # Also keep the latest as `review` for backward compat
            book_state.review = turn_record

            save_book(book_state.id, book_state)

            # If book passes review, we're done
            if verdict == "ready" or not issues:
                logger.info("Book '%s' passed review after %d turn(s) (score: %d/10)",
                           book_state.title, turn_num, overall_score)
                book_state.review["reviewed"] = True
                _transition(book_state, "reviewed")
                book_state.progress["current_step"] = "reviewed"
                book_state.progress["percentage"] = 100
                save_book(book_state.id, book_state)
                return book_state.review_history

        # Max turns reached without passing — mark as reviewed anyway with note
        logger.warning("Book '%s' did not pass review after %d turns", book_state.title, turns_limit)
        book_state.review["reviewed"] = True
        book_state.review["max_turns_reached"] = True
        book_state.review["message"] = f"Review completed after {turns_limit} turns. Some issues may remain."
        _transition(book_state, "reviewed")
        book_state.progress["current_step"] = "reviewed"
        book_state.progress["percentage"] = 100
        save_book(book_state.id, book_state)

        return book_state.review_history

    def _parse_critique(self, raw: str) -> dict:
        """Parse the critique response from the LLM, handling various formats."""
        # Try to extract JSON from the response
        clean = raw.strip()

        # Remove markdown code fences
        if clean.startswith("```"):
            parts = clean.split("```")
            if len(parts) >= 2:
                clean = parts[1]
            first_newline = clean.find("\n")
            if first_newline > 0 and clean[:first_newline].strip().isalpha():
                clean = clean[first_newline + 1:]
            clean = clean.strip()

        # Try JSON parsing
        try:
            data = json.loads(clean)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: parse from text
        result = {"issues": [], "overall_score": 5, "verdict": "ready"}

        # Try to extract score
        score_match = re.search(r'score[:\s]*(\d+)', clean, re.IGNORECASE)
        if score_match:
            result["overall_score"] = int(score_match.group(1))

        # Try to extract issues
        issue_blocks = re.split(r'(?:issue|problem|finding)\s*#?\s*\d+', clean, flags=re.IGNORECASE)
        for block in issue_blocks[1:]:
            chapter_match = re.search(r'chapter[:\s"]*(.+?)[":\s,]', block, re.IGNORECASE)
            type_match = re.search(r'type[:\s"]*(.+?)[":\s,]', block, re.IGNORECASE)
            desc_match = re.search(r'(?:description|problem)[:\s"]*(.+?)[":\s\n]', block, re.IGNORECASE)
            sugg_match = re.search(r'suggestion[:\s"]*(.+?)[":\s\n]', block, re.IGNORECASE)

            if desc_match:
                result["issues"].append({
                    "chapter": chapter_match.group(1).strip().strip('"') if chapter_match else "unknown",
                    "type": type_match.group(1).strip().strip('"') if type_match else "general",
                    "description": desc_match.group(1).strip().strip('"'),
                    "suggestion": sugg_match.group(1).strip().strip('"') if sugg_match else "Review and revise",
                })

        if result["issues"]:
            result["verdict"] = "needs_revision"

        return result

    def _match_chapter_title(self, query: str, chapters: dict) -> Optional[str]:
        """Find the best matching chapter title for a given query string."""
        query_lower = query.lower().strip()
        best_match = None
        best_score = 0

        for title in chapters:
            title_lower = title.lower().strip()
            # Exact match
            if query_lower == title_lower:
                return title
            # Contains match
            if query_lower in title_lower or title_lower in query_lower:
                score = min(len(query_lower), len(title_lower)) / max(len(query_lower), len(title_lower))
                if score > best_score:
                    best_score = score
                    best_match = title

        return best_match if best_score > 0.5 else None
