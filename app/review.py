"""
Book review pipeline: critique → corrections → re-review.

Supports both full-book review and chunked review for long books.
Uses a separate reviewer client if configured.
"""
import logging
from typing import Optional

from app.ai_client import AIClient, ReviewerClient, _extract_content
from app.storage import save_book, load_config
from app.schemas import BookState
from app.status import _transition
from app.parsing import parse_critique, match_chapter_title
from app.generation import _update_progress
from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config — single source of truth
_shared_config = get_default_shared_config()

# Review thresholds from shared config
REVIEW_PASS_SCORE = _shared_config.review.pass_score
REVIEW_WORD_THRESHOLD = _shared_config.review.word_threshold_default
REVIEW_CHUNK_SIZE = _shared_config.review.chunk_size_default


def _get_review_thresholds() -> tuple:
    """Get review thresholds from persisted config, falling back to defaults."""
    persisted = load_config()
    if persisted:
        return persisted.review_word_threshold, persisted.review_chunk_size
    return REVIEW_WORD_THRESHOLD, REVIEW_CHUNK_SIZE


def _build_review_text(book: BookState, chapters: list, turn_num: int) -> str:
    """Build the review prompt text for a set of chapters.

    Args:
        book: The book being reviewed.
        chapters: List of (title, content) tuples to include in the review.
        turn_num: Current review turn number (for prior history injection).

    Returns:
        Formatted review text string ready for the critique prompt.
    """
    tags_str = ", ".join(book.tags) if book.tags else "none specified"
    review_text = f"Book: {book.title}\nGenre: {tags_str}\n\n"
    review_text += f"Summary:\n{book.summary}\n\n"
    review_text += "Outline:\n" + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(book.outline)) + "\n\n"

    # Include chapter summaries for chapters NOT in this chunk (context)
    chunk_titles = {t for t, _ in chapters}
    other_summaries = []
    if book.chapter_summaries:
        for title, summary in book.chapter_summaries.items():
            if title not in chunk_titles:
                other_summaries.append(f"  \u2022 {title}: {summary}")
    if other_summaries:
        review_text += "Other chapter summaries (for context):\n" + "\n".join(other_summaries) + "\n\n"

    # Include the actual content for chapters in this set
    for idx, (title, content_text) in enumerate(chapters, 1):
        review_text += f"\n{'='*60}\nChapter {idx}: {title}\n{'='*60}\n{content_text}"

    # If this is turn > 1, include prior review results for context
    if turn_num > 1 and book.review_history:
        review_text += "\n\n--- Previous Review History ---\n"
        for prev in book.review_history:
            review_text += f"\nTurn {prev['turn']}:\n"
            review_text += f"  Score: {prev.get('overall_score', '?')}/10\n"
            review_text += f"  Verdict: {prev.get('verdict', '?')}\n"
            if prev.get('corrections'):
                for corr in prev['corrections']:
                    review_text += f"  Corrected: '{corr['chapter']}' ({corr['issue_type']})\n"

    return review_text


def _build_revision_context(book: BookState, chapter_title: str) -> tuple:
    """Build the revision prompt context for a single chapter.

    Args:
        book: The book being revised.
        chapter_title: Title of the chapter to revise.

    Returns:
        (system_prompt, user_prompt) tuple ready for the revision request.
    """
    tags_str = ", ".join(book.tags) if book.tags else "none specified"

    # Build prior chapter summaries for context
    prior_context = ""
    if book.chapter_summaries:
        prior_parts = []
        for outline_title in book.outline:
            if outline_title in book.chapter_summaries and outline_title != chapter_title:
                prior_parts.append(f"  \u2022 {outline_title}: {book.chapter_summaries[outline_title]}")
        if prior_parts:
            prior_context = "\nPrior chapter summaries:\n" + "\n".join(prior_parts)

    system_prompt = (
        "You are a skilled fiction writer revising a chapter. Rewrite the chapter to address "
        "the specific issues identified while preserving the core narrative and style. "
        "Ensure consistency with the rest of the book."
    )
    user_prompt = (
        f"Book: {book.title}\nGenre: {tags_str}\n\n"
        f"Book summary:\n{book.summary}\n\n"
        + prior_context + "\n\n"
    )
    return system_prompt, user_prompt


def _record_review_turn(book: BookState, turn_record: dict) -> None:
    """Record a review turn in the book's history and persist."""
    book.review_history.append(turn_record)
    book.review = turn_record
    save_book(book.id, book)


async def review_book(ai_client: AIClient, book: BookState,
                       reviewer_client: Optional[ReviewerClient] = None) -> None:
    """
    Run the review pipeline on a completed book.

    Performs critique → corrections → re-review until the book passes
    (score >= threshold, verdict = 'ready') or max turns is reached.
    """
    if book.status not in ("completed", "reviewing"):
        raise ValueError(
            f"Cannot review book: book is in '{book.status}' status (expected 'completed' or 'reviewing')"
        )

    if not book.chapters or not book.summary:
        raise ValueError("Cannot review: book content is incomplete")

    if book.skip_review:
        logger.info("Review skipped for '%s' (%s)", book.title, book.id)
        _transition(book, "reviewed")
        _update_progress(book, "reviewed", 100)
        save_book(book.id, book)
        return

    if book.status == "completed":
        _transition(book, "reviewing")
        _update_progress(book, "reviewing", 97)
        save_book(book.id, book)

    reviewer = reviewer_client if reviewer_client else ai_client
    turns_limit = book.review_max_turns

    # Initialize review history
    if book.review_history is None:
        book.review_history = []

    logger.info("Starting iterative review for '%s' (max %d turns)...", book.title, turns_limit)

    # Use chunked review for long books to avoid context window overflow
    total_words = sum(len(c.split()) for c in book.chapters.values())
    word_threshold, _ = _get_review_thresholds()
    if total_words > word_threshold or len(book.chapters) > 10:
        logger.info("Book '%s' has %d words/%d chapters - using chunked review",
                     book.title, total_words, len(book.chapters))
        await _chunked_review(reviewer, ai_client, book, turns_limit)
        return

    await _full_review(reviewer, ai_client, book, turns_limit)


async def _full_review(reviewer: AIClient, ai_client: AIClient,
                        book: BookState, turns_limit: int) -> None:
    """Run full-book review: critique entire book → correct → re-review."""
    chapters = list(book.chapters.items())

    for turn_num in range(1, turns_limit + 1):
        logger.info("Review turn %d/%d for '%s'", turn_num, turns_limit, book.title)

        # Update progress for UI
        if turn_num > 1:
            _update_progress(book, f"reviewing (turn {turn_num})",
                             97 + int((turn_num - 1) / turns_limit * 3))
            save_book(book.id, book)

        # Build the full book text for review (using shared helper)
        review_text = _build_review_text(book, chapters, turn_num)

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
                f"Be constructive but honest. Only flag issues that would genuinely affect reader experience. "
                f"If the book is solid (score >= {REVIEW_PASS_SCORE}), set verdict to 'ready' with an empty issues array."
            )},
            {"role": "user", "content": review_text},
        ]

        critique_response = await reviewer.generate_completion(critique_messages, temperature=0.3)
        critique_raw = _extract_content(critique_response)

        # Parse critique response
        critique_data = parse_critique(critique_raw)
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
                if not chapter_title or chapter_title not in book.chapters:
                    # If chapter title doesn't match, try fuzzy match
                    matched = match_chapter_title(chapter_title, book.chapters)
                    if matched:
                        chapter_title = matched
                    else:
                        logger.warning("Could not match issue chapter '%s' to any generated chapter", chapter_title)
                        continue

                if chapter_title in corrected_chapters:
                    continue  # Already corrected this chapter

                description = issue.get("description", "")
                suggestion = issue.get("suggestion", "")

                revision_sys, revision_user = _build_revision_context(book, chapter_title)
                revision_messages = [
                    {"role": "system", "content": revision_sys},
                    {"role": "user", "content": (
                        revision_user +
                        f"Issue identified in '{chapter_title}':\n"
                        f"  Type: {issue.get('type', 'general')}\n"
                        f"  Problem: {description}\n"
                        f"  Suggested fix: {suggestion}\n\n"
                        f"Current chapter content:\n{book.chapters[chapter_title]}\n\n"
                        f"Rewrite this chapter to address the issue. Return only the revised chapter content."
                    )},
                ]

                revision_response = await ai_client.generate_completion(revision_messages, temperature=0.7)
                revised_content = _extract_content(revision_response)

                # Update chapter and regenerate its summary
                book.chapters[chapter_title] = revised_content
                new_summary = await _summarize_chapter(ai_client, revised_content, chapter_title)
                book.chapter_summaries[chapter_title] = new_summary
                corrected_chapters.add(chapter_title)

                corrections.append({
                    "chapter": chapter_title,
                    "issue_type": issue.get("type", "general"),
                    "issue_description": description,
                    "suggestion": suggestion,
                    "corrected": True,
                })

                # Save after each correction
                save_book(book.id, book)

            logger.info("Turn %d: Completed %d corrections", turn_num, len(corrected_chapters))
        else:
            logger.info("Turn %d: Book passed review (score: %d/10)", turn_num, overall_score)

        # Record this turn in history (using shared helper)
        _record_review_turn(book, {
            "turn": turn_num,
            "critique": critique_raw,
            "issues": issues,
            "overall_score": overall_score,
            "verdict": verdict,
            "corrections": corrections,
        })

        # If book passes review, we're done
        if verdict == "ready" or not issues:
            logger.info("Book '%s' passed review after %d turn(s) (score: %d/10)",
                        book.title, turn_num, overall_score)
            book.review["reviewed"] = True
            _transition(book, "reviewed")
            _update_progress(book, "reviewed", 100)
            save_book(book.id, book)
            return

    # Max turns reached without passing - mark as reviewed anyway with note
    logger.warning("Book '%s' did not pass review after %d turns", book.title, turns_limit)
    book.review["reviewed"] = True
    book.review["max_turns_reached"] = True
    book.review["message"] = f"Review completed after {turns_limit} turns. Some issues may remain."
    _transition(book, "reviewed")
    _update_progress(book, "reviewed", 100)
    save_book(book.id, book)


async def _chunked_review(reviewer: AIClient, ai_client: AIClient,
                           book: BookState, turns_limit: int) -> None:
    """Review a long book in chunks to avoid context window overflow.

    For books exceeding REVIEW_WORD_THRESHOLD words or with many
    chapters, reviews are done in batches of REVIEW_CHUNK_SIZE chapters.
    Results are aggregated and corrections applied across all chunks.
    """
    tags_str = ", ".join(book.tags) if book.tags else "none specified"

    # Initialize review history
    if book.review_history is None:
        book.review_history = []

    logger.info("Starting chunked review for '%s' (%d chapters, ~%d words, max %d turns)...",
                book.title, len(book.chapters),
                sum(len(c.split()) for c in book.chapters.values()),
                turns_limit)

    # Split chapters into chunks
    chapters = list(book.chapters.items())
    _, chunk_size = _get_review_thresholds()
    chunks = [chapters[i:i + chunk_size] for i in range(0, len(chapters), chunk_size)]

    for turn_num in range(1, turns_limit + 1):
        logger.info("Chunked review turn %d/%d for '%s'", turn_num, turns_limit, book.title)

        # Update progress for UI
        if turn_num > 1:
            _update_progress(book, f"reviewing (turn {turn_num})",
                             97 + int((turn_num - 1) / turns_limit * 3))
            save_book(book.id, book)

        # Review each chunk
        turn_issues = []
        turn_scores = []
        turn_corrections = []

        for chunk_idx, chunk in enumerate(chunks):
            # Build review text for this chunk (using shared helper)
            review_text = _build_review_text(book, chunk, turn_num)

            # Critique this chunk
            critique_messages = [
                {"role": "system", "content": (
                    "You are a professional book critic and editor. Review the following chapters critically. "
                    "Identify any major issues including plot holes, character inconsistencies, pacing problems, "
                    "continuity errors, tone inconsistencies, and unresolved threads.\n\n"
                    "Return your review as a JSON object with this exact structure:\n"
                    '{"issues": [{"chapter": "chapter_title", "type": "issue_type", "description": "what is wrong", "suggestion": "how to fix"}], "overall_score": 0-10, "verdict": "needs_revision" | "ready"}\n\n'
                    "Only flag issues in the chapters provided above. Score based on these chapters but consider overall book quality."
                )},
                {"role": "user", "content": review_text},
            ]

            critique_response = await reviewer.generate_completion(critique_messages, temperature=0.3)
            critique_raw = _extract_content(critique_response)

            critique_data = parse_critique(critique_raw)
            chunk_issues = critique_data.get("issues", [])
            chunk_score = critique_data.get("overall_score", 5)
            chunk_verdict = critique_data.get("verdict", "needs_revision")

            turn_scores.append(chunk_score)

            logger.info("Chunk %d/%d: score=%d, verdict=%s, %d issues",
                       chunk_idx + 1, len(chunks), chunk_score, chunk_verdict, len(chunk_issues))

            # Filter issues to only include chapters in this chunk
            for issue in chunk_issues:
                chapter_title = issue.get("chapter", "")
                if chapter_title:
                    # Try to match to actual chapter
                    if chapter_title not in book.chapters:
                        matched = match_chapter_title(chapter_title, book.chapters)
                        if matched:
                            issue["chapter"] = matched
                        else:
                            continue
                turn_issues.append(issue)

            # Correct issues in this chunk (using writer client)
            corrected_chapters = set()
            for issue in chunk_issues:
                chapter_title = issue.get("chapter", "")
                if not chapter_title or chapter_title not in book.chapters:
                    continue
                if chapter_title in corrected_chapters:
                    continue

                description = issue.get("description", "")
                suggestion = issue.get("suggestion", "")

                revision_sys, revision_user = _build_revision_context(book, chapter_title)
                revision_messages = [
                    {"role": "system", "content": revision_sys},
                    {"role": "user", "content": (
                        revision_user +
                        f"Issue identified in '{chapter_title}':\n"
                        f"  Type: {issue.get('type', 'general')}\n"
                        f"  Problem: {description}\n"
                        f"  Suggested fix: {suggestion}\n\n"
                        f"Current chapter content:\n{book.chapters[chapter_title]}\n\n"
                        f"Rewrite this chapter to address the issue. Return only the revised chapter content."
                    )},
                ]

                revision_response = await ai_client.generate_completion(revision_messages, temperature=0.7)
                revised_content = _extract_content(revision_response)

                book.chapters[chapter_title] = revised_content
                new_summary = await _summarize_chapter(ai_client, revised_content, chapter_title)
                book.chapter_summaries[chapter_title] = new_summary
                corrected_chapters.add(chapter_title)

                turn_corrections.append({
                    "chapter": chapter_title,
                    "issue_type": issue.get("type", "general"),
                    "issue_description": description,
                    "suggestion": suggestion,
                    "corrected": True,
                })
                save_book(book.id, book)

        # Aggregate results for this turn
        avg_score = int(sum(turn_scores) / len(turn_scores)) if turn_scores else 5
        overall_verdict = "ready" if all(s >= REVIEW_PASS_SCORE for s in turn_scores) else "needs_revision"

        # Record this turn in history (using shared helper)
        _record_review_turn(book, {
            "turn": turn_num,
            "critique": f"Chunked review: {len(chunks)} chunks, avg score {avg_score}/10",
            "issues": turn_issues,
            "overall_score": avg_score,
            "verdict": overall_verdict,
            "corrections": turn_corrections,
        })

        logger.info("Turn %d complete: avg_score=%d, verdict=%s, %d corrections",
                    turn_num, avg_score, overall_verdict, len(turn_corrections))

        # If all chunks pass review, we're done
        if overall_verdict == "ready" or not turn_issues:
            logger.info("Book '%s' passed chunked review after %d turn(s) (avg score: %d/10)",
                        book.title, turn_num, avg_score)
            book.review["reviewed"] = True
            _transition(book, "reviewed")
            _update_progress(book, "reviewed", 100)
            save_book(book.id, book)
            return

    # Max turns reached without passing
    logger.warning("Book '%s' did not pass chunked review after %d turns", book.title, turns_limit)
    book.review["reviewed"] = True
    book.review["max_turns_reached"] = True
    book.review["message"] = f"Review completed after {turns_limit} turns. Some issues may remain."
    _transition(book, "reviewed")
    _update_progress(book, "reviewed", 100)
    save_book(book.id, book)


async def _summarize_chapter(ai_client: AIClient, chapter_content: str, chapter_title: str) -> str:
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

    response = await ai_client.generate_completion(messages, temperature=0.3)
    return _extract_content(response)
