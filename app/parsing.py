"""
Parsing utilities for extracting structured data from LLM responses.

Handles outline parsing (JSON and prose formats), critique parsing
(JSON and text fallbacks), and fuzzy chapter title matching.
"""
import re
import json
import logging
from typing import Dict, List, Optional, Any

from app.ai_client import _extract_content

logger = logging.getLogger(__name__)


def parse_outline(raw: str, default_chapters: List[str]) -> List[str]:
    """
    Parse outline from LLM response, handling JSON, code fences, and prose text.

    Returns a list of chapter titles. Falls back to default chapters
    if no parseable content is found.
    """
    content = _extract_content(raw) if isinstance(raw, dict) else raw
    if not content or not content.strip():
        logger.warning("Empty outline response, using default chapters")
        return list(default_chapters)

    # Try to extract JSON from code fences
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try to find JSON object in text
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        json_str = json_match.group(0) if json_match else None

    # Try JSON parsing
    if json_str:
        try:
            data = json.loads(json_str)
            if "chapters" in data:
                chapters = data["chapters"]
                if isinstance(chapters, list):
                    return [str(c) for c in chapters]
                elif isinstance(chapters, dict):
                    return list(chapters.keys())
        except json.JSONDecodeError:
            pass

    # Fallback: parse numbered lines
    lines = content.strip().split("\n")
    chapters = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Match "Chapter N: Title" or "N. Title" or "N) Title"
        match = re.match(r"(?i)chapter\s+\d+[:\.]\s*(.+)", line)
        if not match:
            match = re.match(r"\d+[\)\.]\s*(.+)", line)
        if match:
            chapters.append(match.group(1).strip())

    if chapters:
        return chapters

    logger.warning("Could not parse outline, using default chapters")
    return list(default_chapters)


def parse_critique(raw: str) -> Dict[str, Any]:
    """
    Parse critique from LLM response, handling JSON and text formats.

    Returns a dict with:
    - issues: list of issue dicts (chapter, type, description, suggestion)
    - overall_score: int (0-10)
    - verdict: 'needs_revision' or 'ready'
    """
    content = _extract_content(raw) if isinstance(raw, dict) else raw
    if not content or not content.strip():
        logger.warning("Empty critique response, using defaults")
        return {"issues": [], "overall_score": 5, "verdict": "ready"}

    # Try to extract JSON from code fences
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try to find JSON object in text
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        json_str = json_match.group(0) if json_match else None

    # Try JSON parsing
    if json_str:
        try:
            data = json.loads(json_str)
            issues = data.get("issues", [])
            if not isinstance(issues, list):
                issues = []
            score = data.get("overall_score", 5)
            verdict = data.get("verdict", "ready")
            return {"issues": issues, "overall_score": int(score), "verdict": verdict}
        except json.JSONDecodeError:
            pass

    # Fallback: parse text format
    issues = []
    score = 5
    verdict = "ready"

    # Extract score
    score_match = re.search(r"(?:overall\s+)?score[:\s]*(\d+)(?:/10)?", content, re.IGNORECASE)
    if score_match:
        score = int(score_match.group(1))

    # Extract verdict
    verdict_match = re.search(r"verdict[:\s]*(\w+)", content, re.IGNORECASE)
    if verdict_match:
        verdict = verdict_match.group(1).lower()

    # Extract issues
    issue_blocks = re.split(r"Issue\s+#\d+", content, flags=re.IGNORECASE)
    for block in issue_blocks[1:]:  # Skip first block (before any issue)
        issue = {}
        chapter_match = re.search(r"chapter[:\s]*(.+?)(?:\n|$)", block, re.IGNORECASE)
        type_match = re.search(r"type[:\s]*(.+?)(?:\n|$)", block, re.IGNORECASE)
        desc_match = re.search(r"description[:\s]*(.+?)(?:\n|$)", block, re.IGNORECASE)
        sugg_match = re.search(r"suggestion[:\s]*(.+?)(?:\n|$)", block, re.IGNORECASE)

        if chapter_match:
            issue["chapter"] = chapter_match.group(1).strip()
        if type_match:
            issue["type"] = type_match.group(1).strip()
        if desc_match:
            issue["description"] = desc_match.group(1).strip()
        if sugg_match:
            issue["suggestion"] = sugg_match.group(1).strip()

        if issue:
            issues.append(issue)

    return {"issues": issues, "overall_score": score, "verdict": verdict}


def match_chapter_title(query: str, chapters: Dict[str, str]) -> Optional[str]:
    """
    Match a chapter title query to the actual chapter title.

    Uses exact match, normalized match, substring match, and token-based
    fuzzy matching in order of preference.
    """
    if not query or not chapters:
        return None

    # Exact match
    if query in chapters:
        return query

    # Normalized exact match
    normalized_query = _normalize_title(query)
    for title in chapters:
        if _normalize_title(title) == normalized_query:
            return title

    # Substring match (either direction, using normalized titles)
    for title in chapters:
        normalized_title = _normalize_title(title)
        if normalized_query in normalized_title:
            return title
        if normalized_title in normalized_query:
            return title

    # Token-based Jaccard similarity
    query_tokens = set(normalized_query.split())
    best_match = None
    best_score = 0

    for title in chapters:
        title_tokens = set(_normalize_title(title).split())
        if query_tokens or title_tokens:
            intersection = query_tokens & title_tokens
            union = query_tokens | title_tokens
            score = len(intersection) / len(union) if union else 0
        else:
            score = 0

        if score > best_score:
            best_score = score
            best_match = title

    return best_match if best_score > 0.3 else None


def _normalize_title(title: str) -> str:
    """Normalize a title for comparison: lowercase, remove punctuation, collapse whitespace."""
    normalized = title.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
