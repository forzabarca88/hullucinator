"""
Parsing utilities for extracting structured data from LLM responses.

Handles outline parsing (JSON, code fences, numbered/bulleted lists,
markdown headings, and plain prose), critique parsing (JSON and text
fallbacks), and fuzzy chapter title matching.
"""
import re
import json
import logging
from typing import Dict, List, Optional, Any

from app.ai_client import _extract_content

logger = logging.getLogger(__name__)


def _extract_balanced_json(text: str) -> Optional[str]:
    """Extract a balanced JSON object or array from text.

    Finds the first '{' or '[' and matches it with its corresponding
    closing bracket, handling nested structures. Returns None if no
    valid JSON is found.
    """
    # Look for the start of a JSON object or array
    start = None
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            start = i
            break
    if start is None:
        return None

    # Walk through text, tracking bracket depth
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            depth += 1
        elif ch in ('}', ']'):
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                # Verify it parses as valid JSON
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None
    return None


def parse_outline(raw: str, default_chapters: List[str]) -> List[str]:
    """
    Parse outline from LLM response, handling JSON, code fences, and
    prose text. Returns a list of chapter titles. Falls back to default
    chapters if no parseable content is found.

    Handles:
    - JSON arrays: ["Chapter 1: Title", ...]
    - JSON objects: {"chapters": [...]}
    - Numbered lists: "1. Title", "Chapter 1: Title", "1) Title"
    - Markdown headings: "# Chapter 1: Title"
    - Bullet lists: "- Title", "* Title"
    - Plain prose with chapter references
    """
    content = _extract_content(raw) if isinstance(raw, dict) else raw
    if not content or not content.strip():
        logger.warning("Empty outline response, using default chapters")
        return list(default_chapters)

    # Clean up markdown code blocks (standalone ```) 
    clean = content.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        if len(parts) >= 2:
            clean = parts[1]
        # Strip language label
        first_newline = clean.find("\n")
        if first_newline > 0 and clean[:first_newline].strip().isalpha():
            clean = clean[first_newline + 1:]
        clean = clean.strip()

    # Try to extract JSON from code fences
    json_str = None
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try to find a top-level JSON object — use a balanced-brace approach
        # to avoid the greedy \{.*\} matching across multiple JSON blocks
        json_str = _extract_balanced_json(content)

    # Try JSON parsing
    if json_str:
        try:
            data = json.loads(json_str)
            if isinstance(data, list):
                chapters = [str(item).strip() for item in data if str(item).strip()]
                if chapters:
                    return chapters
            if "chapters" in data:
                chapters = data["chapters"]
                if isinstance(chapters, list):
                    return [str(c) for c in chapters]
                elif isinstance(chapters, dict):
                    return list(chapters.keys())
        except json.JSONDecodeError:
            pass

    # Fallback: line-based parsing with heuristic marker detection
    lines = content.split("\n")
    chapters = []
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue

        # Skip markdown code fence markers
        if clean_line.startswith("```"):
            continue

        # Skip lines that look like raw JSON fragments (e.g. '"chapters": [')
        # These are artifacts from failed JSON parsing, not real chapter titles
        if re.match(r'^\s*["\{\[]', clean_line):
            continue

        # Detect various list markers
        parsed_title = None

        # "Chapter N: Title" or "Chapter N - Title" or "Chapter N. Title"
        chapter_match = re.match(r"(?i)^(chapter\s+\d+[:\.\-]\s*)(.+)$", clean_line)
        if chapter_match:
            parsed_title = chapter_match.group(2).strip()

        # Numbered: "1. Title", "1) Title"
        num_match = re.match(r"^(\d+[.)]\s+)(.+)$", clean_line)
        if not parsed_title and num_match:
            parsed_title = num_match.group(2).strip()

        # Markdown heading: "# Chapter 1: Title"
        if not parsed_title:
            heading_match = re.match(r"^#{1,6}\s+(.+)$", clean_line)
            if heading_match:
                parsed_title = heading_match.group(1).strip()

        # Bullet: "- Title" or "* Title"
        if not parsed_title:
            bullet_match = re.match(r"^[-*]\s+(.+)$", clean_line)
            if bullet_match:
                parsed_title = bullet_match.group(1).strip()

        # Plain line that looks like a chapter title
        if not parsed_title and len(clean_line) > 3:
            if any(marker in clean_line.lower() for marker in
                    ["chapter", "part", "section", "prologue", "epilogue"]):
                parsed_title = clean_line

        if parsed_title:
            chapters.append(parsed_title)

    if not chapters:
        logger.warning("Could not parse outline, using default chapters")
        return list(default_chapters)

    return chapters


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
    json_str = None
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Use balanced-brace extraction to avoid greedy matching
        json_str = _extract_balanced_json(content)

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
    # Remove hyphens within words (merge connected parts, e.g. "Mid-Point" -> "midpoint")
    normalized = normalized.replace("-", "")
    # Replace remaining punctuation with spaces
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
